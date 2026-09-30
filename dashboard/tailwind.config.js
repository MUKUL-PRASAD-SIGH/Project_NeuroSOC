export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        soc: {
          bg: "#05070d",
          panel: "#0a0e18",
          panelSoft: "#0f1523",
          border: "#1a2233",
          text: "#eef2fa",
          muted: "#8a93a8",
          electric: "#5b93ff",
          // Verdict tones stay within one blue family: bright = threat, mid = review, dim = normal.
          red: "#e6edff",
          amber: "#7ea6ff",
          green: "#46557a",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
        display: ["'Playfair Display'", "Georgia", "serif"],
      },
      boxShadow: {
        panel: "inset 0 1px 0 rgba(255,255,255,0.05), 0 30px 60px -30px rgba(0,0,0,0.85)",
      },
    },
  },
  plugins: [],
};
