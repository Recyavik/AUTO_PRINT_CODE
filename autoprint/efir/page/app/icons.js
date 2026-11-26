// Значки окна программы: линия 1.8, 24×24, цвет — currentColor. Свои, в духе макета.
"use strict";

const P = {
  keyboard: '<rect x="2.5" y="5.5" width="19" height="13" rx="2.5"/><path d="M6.5 9.5h.01M10 9.5h.01M13.5 9.5h.01M17.5 9.5h.01M6.5 12.5h.01M17.5 12.5h.01M10 12.5h4M7.5 15.5h9"/>',
  pin: '<path d="M12 16.5V21"/><path d="M8.5 3.5h7l-1 5.5 3 3V14h-11v-2l3-3z"/>',
  pip: '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><rect x="12" y="11.5" width="6.5" height="5.5" rx="1.2"/>',
  expand: '<path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/>',
  min: '<path d="M6 12h12"/>',
  max: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  restore: '<rect x="5.5" y="8.5" width="10" height="10" rx="1.5"/><path d="M8.5 5.5h8.5a1.5 1.5 0 0 1 1.5 1.5v8.5"/>',
  close: '<path d="M7 7l10 10M17 7L7 17"/>',
  image: '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.7"/><path d="M21 16l-5-5-9.5 8.5"/>',
  activity: '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
  cup: '<path d="M4.5 9h12v5a5 5 0 0 1-5 5h-2a5 5 0 0 1-5-5z"/><path d="M16.5 10.5h1.3a2.3 2.3 0 0 1 0 4.6h-1.3"/><path d="M8.5 3.5v2.5M12.5 3.5v2.5"/>',
  slide: '<rect x="3" y="4.5" width="18" height="13" rx="2.5"/><path d="M10.5 8.5v5l4-2.5z"/><path d="M9 21h6"/>',
  monitor: '<rect x="2.5" y="4" width="19" height="13" rx="2.2"/><path d="M8 20.5h8M12 17v3.5"/>',
  blackout: '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><rect x="6.5" y="8" width="11" height="8" rx="1" fill="currentColor" stroke="none"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
  play: '<path d="M7 4.5v15l12-7.5z"/>',
  pause: '<path d="M9 5.5v13M15 5.5v13"/>',
  skip: '<path d="M5.5 5.5l10 6.5-10 6.5z"/><path d="M19 5.5v13"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  sliders: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
  book: '<path d="M5 4.5h11a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h11"/>',
  radio: '<circle cx="12" cy="12" r="2"/><path d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14"/>',
  copy: '<rect x="8.5" y="8.5" width="11.5" height="11.5" rx="2"/><path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 1 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 1 0 5.7 5.7l1-1"/>',
  speak: '<path d="M20.5 12a8.5 8.5 0 0 1-12.3 7.6L3.5 21l1.4-4.5A8.5 8.5 0 1 1 20.5 12z"/>',
  pointer: '<path d="M5 4l13.5 6.5-6 1.8-2.3 6.2z"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.1-2.4 3.7"/><path d="M12 17.3h.01"/>',
  alert: '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17.3h.01"/>',
  upload: '<path d="M12 15V4M7.5 8.5L12 4l4.5 4.5"/><path d="M4 15v3.5A2.5 2.5 0 0 0 6.5 21h11a2.5 2.5 0 0 0 2.5-2.5V15"/>',
  download: '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5"/><path d="M4 15v3.5A2.5 2.5 0 0 0 6.5 21h11a2.5 2.5 0 0 0 2.5-2.5V15"/>',
  sparkles: '<path d="M12 3l1.8 4.7 4.7 1.8-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/><path d="M19 15l.8 2.2 2.2.8-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  clipboard: '<rect x="6" y="4.5" width="12" height="16.5" rx="2"/><path d="M9 4.5V3h6v1.5M9 10h6M9 14h4"/>',
  pencil: '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
  trash: '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
  grip: '<circle cx="9" cy="6" r=".9"/><circle cx="15" cy="6" r=".9"/><circle cx="9" cy="12" r=".9"/><circle cx="15" cy="12" r=".9"/><circle cx="9" cy="18" r=".9"/><circle cx="15" cy="18" r=".9"/>',
  "chevron-down": '<path d="M6 9l6 6 6-6"/>',
  "chevron-up": '<path d="M6 15l6-6 6 6"/>',
  "chevron-left": '<path d="M15 6l-6 6 6 6"/>',
  "chevron-right": '<path d="M9 6l6 6-6 6"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  file: '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5"/>',
  folder: '<path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h4.5l2 2.5H19a1.5 1.5 0 0 1 1.5 1.5v9.5A1.5 1.5 0 0 1 19 20H5a1.5 1.5 0 0 1-1.5-1.5z"/>',
  bug: '<path d="M9 7.5V6a3 3 0 0 1 6 0v1.5"/><rect x="7" y="7.5" width="10" height="12" rx="5"/><path d="M12 11v8.5M3.5 13h3.5M17 13h3.5M5 8.5l2.5 1.5M19 8.5L16.5 10M5 19l2.5-2M19 19l-2.5-2"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16.5v-5M12 8h.01"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.5 4.5L20 16"/><path d="M20 20v-4h-4"/>',
  layers: '<path d="M12 3.5l9 4.5-9 4.5-9-4.5z"/><path d="M3 12.5l9 4.5 9-4.5"/><path d="M3 16.5l9 4.5 9-4.5"/>',
  logout: '<path d="M14.5 4H18a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3.5"/><path d="M10 16l-4-4 4-4M6 12h10"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  volume: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  side: '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M9 4.5v15"/>',
  top: '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M3 9.5h18"/>',
  hidden: '<rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="M8 12h8"/>',
  zoom: '<path d="M4 18L9 6l5 12M5.7 14h6.6"/><path d="M15.5 18l3-7 3 7M16.4 16h4.2"/>',
  more: '<circle cx="5.5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="18.5" cy="12" r="1"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  home: '<path d="M4 11l8-6.5 8 6.5"/><path d="M6 9.5V20h12V9.5"/>',
  undo: '<path d="M9 14L4.5 9.5 9 5"/><path d="M5 9.5h9a5.5 5.5 0 0 1 0 11h-3"/>',
  open: '<path d="M14 4.5h5.5V10M19.5 4.5l-8 8"/><path d="M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
  printer: '<path d="M7 9V4h10v5"/><rect x="3.5" y="9" width="17" height="8" rx="2"/><path d="M7 14h10v6H7z"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  wand: '<path d="M4 20L15 9M13 7l4 4"/><path d="M18 3v3M16.5 4.5h3M7 4v2M6 5h2M20 13v2M19 14h2"/>',
  code: '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 5l-3 14"/>',
  stage: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2M10 2.5h4"/>',
};

const NS = "http://www.w3.org/2000/svg";

export function icon(name, cls = "") {
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("aria-hidden", "true");
  s.setAttribute("class", "i" + (cls ? " " + cls : ""));
  s.innerHTML = P[name] || P.info;
  return s;
}

export const ICON_NAMES = Object.keys(P);
