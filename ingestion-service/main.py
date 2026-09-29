"""
main.py — NeuroShield Ingestion Service
Phase 1.2 per MASTER_PLAN.md

FIXES vs v1:
  1. build_producer() retry delay: 5s → 15s  (matches kafka_setup)
  2. PCAP mode: no-file case → synthetic data generator (keeps container live
     and Kafka verifiable without real PCAP files on first run)
  3. CORS: added GET to allow_methods (health endpoint was blocked)
  4. DATA_DIR auto-created on startup (no more path-not-found crash)
  5. Synthetic generator sends every 2s with realistic dummy values

CHECKPOINT:
  docker-compose exec kafka kafka-console-consumer \
    --topic raw-packets --bootstrap-server kafka:9092 --max-messages 5
  → Should see JSON within seconds even with NO pcap files present.

Three concurrent ingestion modes publish to Kafka topic 'raw-packets':
  - PCAP mode      : reads .pcap files from DATA_DIR using Scapy (streaming)
  - NetFlow mode   : UDP listener on port 2055 for JSON NetFlow records
  - Bank Portal    : FastAPI POST /ingest for browser behavioral events
  - Synthetic mode : auto-generated benign traffic when no PCAP files exist
"""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import math
import os
import random
import socket
import threading
import time
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from fastapi.middleware.cors import CORSMiddleware
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable
from pydantic import BaseModel, Field

# ─── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ingestion] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ─── config ───────────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
INGESTION_MODE  = os.getenv("INGESTION_MODE", "all").lower()
DATA_DIR        = os.getenv("DATA_DIR", "/data/pcap")
INGESTION_SOURCE_ID = os.getenv("INGESTION_SOURCE_ID", "ingestion-service").strip()
TOPIC           = "raw-packets"
LOG_EVERY       = 1000

if not INGESTION_SOURCE_ID or len(INGESTION_SOURCE_ID) > 116:
    raise ValueError("INGESTION_SOURCE_ID must contain 1 to 116 characters.")

# Ensure DATA_DIR exists — FIX: path-not-found crash on first run
os.makedirs(DATA_DIR, exist_ok=True)


# ─── Kafka producer ───────────────────────────────────────────────────────────
def build_producer() -> KafkaProducer:
    """Connect to Kafka with 10 retries × 15s = 150s total wait."""
    max_attempts = int(os.getenv("KAFKA_PRODUCER_RETRIES", "10"))
    delay        = int(os.getenv("KAFKA_PRODUCER_DELAY",   "15"))  # ↑ from 5s

    for attempt in range(1, max_attempts + 1):
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks="all",
                retries=5,
                linger_ms=10,          # small batch window for throughput
                compression_type="gzip",
            )
            log.info("✅ Kafka producer connected (attempt %d/%d).", attempt, max_attempts)
            return producer
        except NoBrokersAvailable:
            log.warning("Kafka not ready (%d/%d). Waiting %ds…", attempt, max_attempts, delay)
            if attempt < max_attempts:
                time.sleep(delay)
            else:
                log.error(
                    "❌ Could not connect Kafka producer after %d attempts. "
                    "Verify: docker-compose ps kafka",
                    max_attempts,
                )
                raise
    raise RuntimeError("Unreachable")


# ─── publish helper ───────────────────────────────────────────────────────────
_published_count = 0
_count_lock = threading.Lock()

EVENTS_PUBLISHED = Counter("neurosoc_ingestion_events_published_total", "Events published to Kafka", ["mode"])


def publish(producer: KafkaProducer, record: dict[str, Any]) -> None:
    producer.send(TOPIC, value=record)
    EVENTS_PUBLISHED.labels(mode=INGESTION_MODE).inc()
    with _count_lock:
        global _published_count
        _published_count += 1
        if _published_count % LOG_EVERY == 0:
            log.info("📤 Published %d packets to '%s'.", _published_count, TOPIC)


def _packet_identity(
    packet_id: str,
    source: str,
    correlation_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Attach stable source and retry identity metadata to one packet event."""
    return {
        "schema_version": "1.1",
        "event_type": "network.packet",
        "source_id": f"{INGESTION_SOURCE_ID}:{source}",
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key or f"network.packet:{packet_id}",
    }


def _bounded_int(value: Any, name: str, minimum: int, maximum: int | None = None) -> int:
    parsed = int(value)
    if parsed < minimum or (maximum is not None and parsed > maximum):
        raise ValueError(f"NetFlow {name} is outside the supported range.")
    return parsed


def _event_timestamp(value: Any) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError("Event timestamp must be a finite non-negative number.")
    return parsed


# ─── TCP flag helpers ─────────────────────────────────────────────────────────
def _flags_from_scapy(pkt) -> dict[str, bool]:
    flags = {"SYN": False, "ACK": False, "FIN": False, "RST": False}
    try:
        from scapy.layers.inet import TCP
        if pkt.haslayer(TCP):
            f = pkt[TCP].flags
            flags["SYN"] = bool(f & 0x02)
            flags["ACK"] = bool(f & 0x10)
            flags["FIN"] = bool(f & 0x01)
            flags["RST"] = bool(f & 0x04)
    except Exception:
        pass
    return flags


def _protocol_str(pkt) -> str:
    try:
        from scapy.layers.inet import TCP, UDP
        if pkt.haslayer(TCP):  return "TCP"
        if pkt.haslayer(UDP):  return "UDP"
    except Exception:
        pass
    return "OTHER"


# ─── PCAP MODE ────────────────────────────────────────────────────────────────
def run_pcap_mode(producer: KafkaProducer) -> None:
    """Stream packets from all .pcap files in DATA_DIR.
    FIX: if no files found, falls into synthetic generator instead of returning.
    """
    try:
        from scapy.utils import PcapReader
        from scapy.layers.inet import IP
    except ImportError:
        log.error("scapy not installed — PCAP mode unavailable. Falling back to synthetic.")
        run_synthetic_mode(producer)
        return

    pattern = os.path.join(DATA_DIR, "*.pcap")
    pcap_files = sorted(glob.glob(pattern))

    if not pcap_files:
        # FIX: was 'return' — now falls back to synthetic so container stays useful
        log.warning(
            "⚠️  No .pcap files in %s. "
            "Starting SYNTHETIC generator — place .pcap files there to use real data.",
            DATA_DIR,
        )
        run_synthetic_mode(producer)
        return

    log.info("Found %d PCAP file(s) in %s.", len(pcap_files), DATA_DIR)
    for pcap_file in pcap_files:
        log.info("Reading PCAP: %s", pcap_file)
        with PcapReader(pcap_file) as reader:
            for pkt in reader:
                try:
                    if not pkt.haslayer(IP):
                        continue
                    ip = pkt[IP]
                    packet_id = str(uuid.uuid4())
                    record = {
                        **_packet_identity(packet_id, "pcap"),
                        "packet_id": packet_id,
                        "timestamp": float(pkt.time),
                        "src_ip":   ip.src,
                        "dst_ip":   ip.dst,
                        "src_port": int(getattr(pkt, "sport", 0) or 0),
                        "dst_port": int(getattr(pkt, "dport", 0) or 0),
                        "protocol": _protocol_str(pkt),
                        "length":   len(pkt),
                        "flags":    _flags_from_scapy(pkt),
                        "ttl":      int(ip.ttl),
                        "source":   "pcap",
                    }
                    publish(producer, record)
                except Exception as exc:
                    log.debug("Skipping malformed packet: %s", exc)
    log.info("PCAP mode: finished all files. Switching to synthetic.")
    run_synthetic_mode(producer)  # keep container alive after PCAP exhausted


# ─── SYNTHETIC MODE ───────────────────────────────────────────────────────────
_PRIVATE_NETS = ["10.0.0.", "192.168.1.", "172.16.0."]
_PUBLIC_NETS  = ["8.8.8.", "1.1.1.", "185.220.101."]
_PROTOCOLS    = ["TCP", "UDP"]


def _fake_packet(source: str = "synthetic") -> dict[str, Any]:
    """Generate a realistic-looking benign network packet record."""
    src_net = random.choice(_PRIVATE_NETS)
    dst_net = random.choice(_PUBLIC_NETS + _PRIVATE_NETS)
    proto   = random.choice(_PROTOCOLS)
    syn     = proto == "TCP" and random.random() < 0.1
    packet_id = str(uuid.uuid4())
    return {
        **_packet_identity(packet_id, source),
        "packet_id": packet_id,
        "timestamp": time.time(),
        "src_ip":    src_net + str(random.randint(1, 254)),
        "dst_ip":    dst_net + str(random.randint(1, 254)),
        "src_port":  random.randint(1024, 65535),
        "dst_port":  random.choice([80, 443, 22, 3306, 5432, 6379]),
        "protocol":  proto,
        "length":    random.randint(40, 1500),
        "flags":     {"SYN": syn, "ACK": not syn, "FIN": False, "RST": False},
        "ttl":       random.choice([64, 128, 255]),
        "source":    source,
    }


def run_synthetic_mode(producer: KafkaProducer, interval: float = 2.0) -> None:
    """Emit synthetic benign packets forever (2/sec by default).

    CHECKPOINT: with no PCAP files, this keeps the container alive and
    Kafka verifiable. Check with:
      docker-compose exec kafka kafka-console-consumer \\
        --topic raw-packets --bootstrap-server kafka:9092 --max-messages 5
    """
    log.info("🤖 Synthetic generator running at %.1f packets/sec.", 1.0 / interval)
    while True:
        try:
            publish(producer, _fake_packet())
        except Exception as exc:
            log.error("Synthetic publish error: %s", exc)
        time.sleep(interval)


# ─── NETFLOW MODE ─────────────────────────────────────────────────────────────
def run_netflow_mode(producer: KafkaProducer) -> None:
    """Listen on UDP 2055 for JSON NetFlow records."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", 2055))
    log.info("📡 NetFlow UDP listener on 0.0.0.0:2055")

    while True:
        try:
            data, addr = sock.recvfrom(65535)
            try:
                flow = json.loads(data.decode("utf-8"))
            except json.JSONDecodeError:
                log.debug("Non-JSON UDP payload from %s — skipping.", addr)
                continue
            flags = flow.get("flags", {})
            if not isinstance(flags, dict):
                flags = {}
            packet_id = str(uuid.uuid4())
            record = {
                **_packet_identity(packet_id, "netflow"),
                "packet_id": packet_id,
                "timestamp": _event_timestamp(flow.get("timestamp", time.time())),
                "src_ip":    str(flow.get("src_ip") or "0.0.0.0")[:64],
                "dst_ip":    str(flow.get("dst_ip") or "0.0.0.0")[:64],
                "src_port":  _bounded_int(flow.get("src_port", 0), "src_port", 0, 65535),
                "dst_port":  _bounded_int(flow.get("dst_port", 0), "dst_port", 0, 65535),
                "protocol":  str(flow.get("protocol") or "OTHER")[:32],
                "length":    _bounded_int(flow.get("length", 0), "length", 0),
                "flags":     {str(name)[:32]: bool(value) for name, value in flags.items()},
                "ttl":       _bounded_int(flow.get("ttl", 0), "ttl", 0, 255),
                "source":    "netflow",
            }
            publish(producer, record)
        except Exception as exc:
            log.error("NetFlow listener error: %s", exc)


# ─── BANK PORTAL MODE — FastAPI ───────────────────────────────────────────────
app = FastAPI(title="NeuroShield Ingestion API", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],   # FIX: GET was missing → /health blocked
    allow_headers=["*"],
)

_producer_ref: KafkaProducer | None = None


class IngestEvent(BaseModel):
    src_ip: str = Field(default="0.0.0.0", min_length=1, max_length=64)
    dst_ip: str = Field(default="0.0.0.0", min_length=1, max_length=64)
    src_port: int = Field(default=0, ge=0, le=65535)
    dst_port: int = Field(default=0, ge=0, le=65535)
    protocol: str = Field(default="OTHER", min_length=1, max_length=32)
    length: int = Field(default=0, ge=0)
    flags: dict[str, bool] = Field(default_factory=dict)
    ttl: int = Field(default=64, ge=0, le=255)
    extra: dict[str, Any] = Field(default_factory=dict)  # page events, behavioral signals


class IngestRequest(BaseModel):
    events:     list[IngestEvent]
    session_id: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(default=None, max_length=256)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


@app.post("/ingest")
async def ingest_endpoint(req: IngestRequest):
    if _producer_ref is None:
        return {"status": "error", "detail": "Kafka producer not initialised"}
    loop = asyncio.get_event_loop()
    published = 0
    for index, event in enumerate(req.events):
        packet_id = str(uuid.uuid4())
        request_event_key = (
            f"{req.idempotency_key}:{index}"
            if req.idempotency_key is not None
            else None
        )
        record = {
            **_packet_identity(packet_id, "bank_portal", req.session_id, request_event_key),
            "packet_id":  packet_id,
            "timestamp":  time.time(),
            "src_ip":     event.src_ip,
            "dst_ip":     event.dst_ip,
            "src_port":   event.src_port,
            "dst_port":   event.dst_port,
            "protocol":   event.protocol,
            "length":     event.length,
            "flags":      event.flags,
            "ttl":        event.ttl,
            "source":     "bank_portal",
            "session_id": req.session_id,
            "user_id":    req.user_id,
            "extra":      event.extra,
        }
        await loop.run_in_executor(None, publish, _producer_ref, record)
        published += 1
    return {"status": "ok", "published": published}


@app.get("/health")
async def health():
    return {
        "status":     "ok",
        "service":    "ingestion",
        "kafka":      KAFKA_BOOTSTRAP,
        "data_dir":   DATA_DIR,
        "mode":       INGESTION_MODE,
        "published":  _published_count,
    }


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/stats")
async def stats():
    return {
        "published_total": _published_count,
        "pcap_dir":        DATA_DIR,
        "pcap_files":      len(glob.glob(os.path.join(DATA_DIR, "*.pcap"))),
    }


# ─── ENTRYPOINT ───────────────────────────────────────────────────────────────
def main() -> None:
    global _producer_ref
    producer = build_producer()
    _producer_ref = producer

    threads: list[threading.Thread] = []

    if INGESTION_MODE in ("pcap", "all"):
        t = threading.Thread(target=run_pcap_mode, args=(producer,), daemon=True, name="pcap")
        t.start()
        threads.append(t)

    if INGESTION_MODE in ("netflow", "all"):
        t = threading.Thread(target=run_netflow_mode, args=(producer,), daemon=True, name="netflow")
        t.start()
        threads.append(t)

    if INGESTION_MODE in ("bank_portal", "all"):
        log.info("🌐 Bank Portal HTTP ingestion on port 8080…")
        uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
    else:
        # No FastAPI — block until threads die (they don't, they loop forever)
        for t in threads:
            t.join()


if __name__ == "__main__":
    main()
