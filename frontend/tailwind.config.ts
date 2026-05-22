import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        navy: {
          50: "#f0f1f7",
          100: "#d8dbe9",
          200: "#a8aecf",
          300: "#7882b5",
          400: "#48569b",
          500: "#2e3c81",
          600: "#1e2761",
          700: "#181f4d",
          800: "#121839",
          900: "#0c1025",
        },
        gold: {
          50: "#fef8e7",
          100: "#fdebb7",
          200: "#fadc88",
          300: "#f8ce58",
          400: "#f6c43d",
          500: "#f4b942",
          600: "#d99a26",
          700: "#a8761d",
          800: "#785214",
          900: "#492d0b",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "Menlo", "Monaco", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
