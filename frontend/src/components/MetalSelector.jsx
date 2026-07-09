import { METAL_TICKER } from "../theme.js"

export default function MetalSelector({ metals, selected, onChange }) {
  return (
    <div className="pf-tabs" role="group" aria-label="Metal">
      {metals.map((metal) => (
        <button
          key={metal}
          type="button"
          className="pf-tab"
          style={{ "--metal-color": `var(--c-${metal})` }}
          onClick={() => onChange(metal)}
          aria-pressed={metal === selected}
        >
          {metal}
          <span className="pf-tab-ticker">{METAL_TICKER[metal]}</span>
        </button>
      ))}
    </div>
  )
}
