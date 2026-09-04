// Crisp line icons from inline SVG — the same 24x24 / 1.9px-stroke family
// as the desktop app's clearscanner/ui/icons.py, so the two builds match.
// <Icon name="crop" /> — stroke follows currentColor.

const PATHS = {
  plus: 'M12 5v14M5 12h14',
  'rotate-left': 'M3 8h9a6 6 0 1 1-6 6 M3 4v4h4',
  'rotate-right': 'M21 8h-9a6 6 0 1 0 6 6 M21 4v4h-4',
  check: 'M4 12.5l5 5L20 6.5',
  x: 'M6 6l12 12M18 6L6 18',
  trash: 'M4 7h16M10 4h4M6 7l1 13h10l1-13M10 11v6M14 11v6',
  sliders: 'M4 8h10M18 8h2M4 16h4M12 16h8',
  text: 'M5 6h14M5 6v-1M19 6v-1M12 6v13M9 19h6',
  print: 'M7 9V4h10v5M7 17H5V9h14v8h-2M7 14h10v6H7z',
  download: 'M12 4v11M7 11l5 5 5-5M5 20h14',
  crop: 'M7 3v14h14M3 7h14v14',
  camera: 'M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z',
  'chevron-left': 'M15 18l-6-6 6-6',
  grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  info: 'M12 11v5M12 8h.01',
  image: 'M4 17l5-5 4 4 3-3 4 4',
  layers: 'M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5M3 17l9 5 9-5',
  reset: 'M3 12a9 9 0 1 0 3-6.7M3 4v4h4',
  scan: 'M4 8V5a1 1 0 0 1 1-1h3M20 8V5a1 1 0 0 0-1-1h-3M4 16v3a1 1 0 0 0 1 1h3M20 16v3a1 1 0 0 1-1 1h-3M4 12h16',
  sparkle: 'M12 3l1.8 4.7L18.5 9.5 13.8 11.3 12 16l-1.8-4.7L5.5 9.5l4.7-1.8z',
}

// icons that need an extra sub-shape beyond the main path
const EXTRA = {
  sliders: (
    <>
      <circle cx="16" cy="8" r="2.3" />
      <circle cx="10" cy="16" r="2.3" />
    </>
  ),
  info: <circle cx="12" cy="12" r="9" />,
  image: <><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="8.5" cy="9.5" r="1.6" /></>,
  camera: <circle cx="12" cy="13" r="4" />,
}

export function Icon({ name, size = 18, strokeWidth = 1.9, ...rest }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {EXTRA[name]}
      <path d={PATHS[name] || ''} />
    </svg>
  )
}

// kept so main.jsx / older imports don't break; no sprite needed anymore.
export function IconSprite() {
  return null
}
