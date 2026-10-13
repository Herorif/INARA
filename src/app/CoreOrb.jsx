export default function CoreOrb({
  active,
  quiet
}) {
  return <div className={`core-orb ${active ? 'is-active' : ''} ${quiet ? 'is-quiet' : ''}`} aria-hidden="true">
        <div className="orb-halo" />
        <svg viewBox="0 0 360 360" className="orb-instrument">
            <defs><radialGradient id="core-light"><stop stopColor="#b4fcff" /><stop offset=".4" stopColor="#59dcea" /><stop offset="1" stopColor="#13839a" /></radialGradient></defs>
            <g className="orb-ring"><circle cx="180" cy="180" r="150" /><circle cx="180" cy="180" r="145" strokeDasharray="2 9" />
                <circle cx="180" cy="180" r="134" strokeDasharray="120 90 40 90" className="ring-accent" /></g>
            <g className="orb-inner"><circle cx="180" cy="180" r="115" strokeDasharray="260 60" /><circle cx="180" cy="180" r="106" strokeDasharray="1 5" /></g>
            <path d="M30 180H66M294 180H330M180 30V66M180 294V330" className="orb-crosshair" />
            <circle cx="180" cy="180" r="88" className="orb-disc" />
            <circle cx="180" cy="180" r="76" className="orb-fine" />
            <path className="orb-glyph" d="M157 141h46v9h-17v60h17v9h-46v-9h17v-60h-17z" fill="url(#core-light)" stroke="none" />
            <g className="orb-dots"><circle cx="180" cy="30" r="3" /><circle cx="330" cy="180" r="3" /><circle cx="180" cy="330" r="3" /><circle cx="30" cy="180" r="3" /></g>
        </svg>
        <span className="orb-coordinate coord-a">NEURAL INTERFACE</span><span className="orb-coordinate coord-b">CORE / 01</span>
        <div className="orb-caption"><span className="status-dot" />{active ? 'PROCESSING' : 'STANDING BY'}</div>
    </div>;
}
