/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",

  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],

  theme: {
    container: {
      center: true,
      padding: {
        DEFAULT: "1rem",
        sm: "2rem",
        lg: "4rem",
        xl: "5rem",
        "2xl": "6rem",
      },
    },

    extend: {
      colors: {
        primary: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          800: "#1e40af",
          900: "#1e3a8a",
        },

        success: {
          50: "#ecfdf5",
          100: "#d1fae5",
          500: "#10b981",
          600: "#059669",
          700: "#047857",
        },

        warning: {
          50: "#fffbeb",
          100: "#fef3c7",
          500: "#f59e0b",
          600: "#d97706",
          700: "#b45309",
        },

        danger: {
          50: "#fef2f2",
          100: "#fee2e2",
          500: "#ef4444",
          600: "#dc2626",
          700: "#b91c1c",
        },

        info: {
          50: "#ecfeff",
          100: "#cffafe",
          500: "#06b6d4",
          600: "#0891b2",
          700: "#0e7490",
        },
      },

      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],

        display: [
          "Poppins",
          "sans-serif",
        ],
      },

      spacing: {
        18: "4.5rem",
        22: "5.5rem",
        26: "6.5rem",
        30: "7.5rem",
        72: "18rem",
        84: "21rem",
        96: "24rem",
      },

      borderRadius: {
        xs: "0.25rem",
        sm: "0.5rem",
        md: "0.75rem",
        lg: "1rem",
        xl: "1.25rem",
        "2xl": "1.5rem",
        "3xl": "2rem",
      },

      boxShadow: {
        card: `
          0 1px 3px rgba(0,0,0,0.1),
          0 1px 2px rgba(0,0,0,0.06)
        `,

        soft: `
          0 4px 12px rgba(0,0,0,0.08)
        `,

        dashboard: `
          0 10px 25px rgba(0,0,0,0.08)
        `,

        glow: `
          0 0 25px rgba(37,99,235,.35)
        `,
      },

      keyframes: {
        fadeIn: {
          from: {
            opacity: "0",
          },
          to: {
            opacity: "1",
          },
        },

        slideUp: {
          from: {
            opacity: "0",
            transform:
              "translateY(20px)",
          },
          to: {
            opacity: "1",
            transform:
              "translateY(0)",
          },
        },

        slideDown: {
          from: {
            opacity: "0",
            transform:
              "translateY(-20px)",
          },
          to: {
            opacity: "1",
            transform:
              "translateY(0)",
          },
        },

        pulseSlow: {
          "0%, 100%": {
            opacity: "1",
          },
          "50%": {
            opacity: ".6",
          },
        },

        bounceSlow: {
          "0%, 100%": {
            transform:
              "translateY(0)",
          },
          "50%": {
            transform:
              "translateY(-10px)",
          },
        },

        shimmer: {
          "0%": {
            backgroundPosition:
              "-1000px 0",
          },

          "100%": {
            backgroundPosition:
              "1000px 0",
          },
        },
      },

      animation: {
        fadeIn:
          "fadeIn 0.5s ease-in-out",

        slideUp:
          "slideUp 0.4s ease-out",

        slideDown:
          "slideDown 0.3s ease-out",

        pulseSlow:
          "pulseSlow 2s infinite",

        bounceSlow:
          "bounceSlow 3s infinite",

        shimmer:
          "shimmer 2s linear infinite",
      },

      backgroundImage: {
        dashboard:
          "linear-gradient(135deg,#2563eb 0%,#7c3aed 100%)",

        card:
          "linear-gradient(135deg,#ffffff 0%,#f8fafc 100%)",

        glass:
          "linear-gradient(135deg,rgba(255,255,255,.15),rgba(255,255,255,.05))",
      },

      screens: {
        xs: "480px",
      },

      minHeight: {
        content:
          "calc(100vh - 4rem)",
      },

      zIndex: {
        60: "60",
        70: "70",
        80: "80",
        90: "90",
      },
    },
  },

  plugins: [],
};