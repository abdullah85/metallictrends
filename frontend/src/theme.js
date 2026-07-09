// Mirrors the CSS custom properties in index.css (which themselves mirror
// web/index.html's design tokens). Recharts needs literal color values, not
// var(--...), since it draws to SVG via inline style/attribute props.
export const COLORS = {
  bg: "#0f0f0e",
  bgAlt: "#151513",
  card: "#1a1a17",
  ink: "#f1efe8",
  inkSoft: "#b3aea3",
  inkFaint: "#746f64",
  rule: "#2d2c27",
  gold1: "#d9af5c",
  gold2: "#8c6c2e",
  cGold: "#ab7225",
  cSilver: "#5988c4",
  cPlatinum: "#009d9e",
  cPalladium: "#b5694f",
  good: "#5cae7f",
  bad: "#d97b64",
}

export const METAL_ACCENT = {
  gold: COLORS.cGold,
  silver: COLORS.cSilver,
  platinum: COLORS.cPlatinum,
  palladium: COLORS.cPalladium,
}

export const METAL_TICKER = {
  gold: "XAU",
  silver: "XAG",
  platinum: "XPT",
  palladium: "XPD",
}

export function capitalize(word) {
  return word.charAt(0).toUpperCase() + word.slice(1)
}

export const tooltipStyle = {
  background: COLORS.bgAlt,
  border: `1px solid ${COLORS.rule}`,
  borderRadius: 4,
  fontSize: 12.5,
}

export const tooltipLabelStyle = { color: COLORS.inkFaint }
export const tooltipItemStyle = { color: COLORS.ink }
