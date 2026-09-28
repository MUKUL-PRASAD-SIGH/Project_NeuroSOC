export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        soc: {
          bg: "#0b0f19",
          panel: "#111726",
          panelSoft: "#161d2f",
          border: "#232c40",
          text: "#e6ebf4",
          muted: "#8a96ab",
          electric: "#4fa8f7",
          red: "#ef5b67",
          amber: "#e9a93b",
          green: "#3cc28f",
        },
      },
      fontFamily: {
        sans: ["Inter", "'IBM Plex Sans'", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
        display: ["Inter", "system-ui", "sans-serif"],
      },
      boxShadow: {
        panel: "0 1px 0 rgba(255,255,255,0.03) inset, 0 8px 24px rgba(0,0,0,0.25)",
      },
    },
  },
  plugins: [],
};
