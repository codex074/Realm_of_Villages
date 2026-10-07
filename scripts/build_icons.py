#!/usr/bin/env python3
"""Generate web/img/icons.svg: one hand-drawn style sprite (64x64 symbols, brown ink outline)."""

INK = "#3b2a1a"
WOOD, WOOD_L = "#a8743f", "#d9a566"
STONE, STONE_L = "#9aa0a6", "#c9cdd1"
IRON, IRON_L = "#5d7fa6", "#a9c0da"
GOLD, GOLD_L = "#d6a935", "#f1d77a"
GREEN, GREEN_L = "#6a994e", "#a5cc83"
RED, RED_L = "#a63d3d", "#d98a7a"
CREAM, SAND = "#f1e6c8", "#d9c79a"
BLUE = "#4a6fa5"

S = {}
# ---- resources
S["wood"] = f'''<rect x="8" y="22" width="40" height="22" rx="4" fill="{WOOD}"/><ellipse cx="48" cy="33" rx="8" ry="11" fill="{WOOD_L}"/><ellipse cx="48" cy="33" rx="4" ry="6" fill="none"/><path d="M14 28h24M14 38h26" fill="none" stroke-width="1.6"/><path d="M12 46l-3 6M44 46l3 6" fill="none"/>'''
S["stone"] = f'''<path d="M8 46l6-20 14-10 18 6 10 16-6 12z" fill="{STONE}"/><path d="M28 16l-4 14 10 6 12-8M24 30l-10-4M34 36l-2 16" fill="none" stroke-width="1.6"/><path d="M16 36l8-2" fill="none" stroke="{STONE_L}" stroke-width="3"/>'''
S["iron"] = f'''<path d="M6 40l8-18h36l8 18z" fill="{IRON}"/><path d="M6 40h52v10H6z" fill="{IRON_L}"/><path d="M18 26h22" fill="none" stroke="{IRON_L}" stroke-width="3"/><path d="M14 45h36" fill="none" stroke-width="1.6"/>'''
S["food"] = f'''<path d="M32 56V20" fill="none" stroke-width="3"/><g fill="{GOLD}"><ellipse cx="32" cy="14" rx="4" ry="8"/><ellipse cx="22" cy="22" rx="4" ry="8" transform="rotate(-35 22 22)"/><ellipse cx="42" cy="22" rx="4" ry="8" transform="rotate(35 42 22)"/><ellipse cx="22" cy="34" rx="4" ry="8" transform="rotate(-35 22 34)"/><ellipse cx="42" cy="34" rx="4" ry="8" transform="rotate(35 42 34)"/></g>'''
# ---- fields
S["woodcutter"] = f'''<path d="M18 54L40 14" fill="none" stroke="{WOOD}" stroke-width="5"/><path d="M18 54L40 14" fill="none" stroke-width="1.4"/><path d="M36 10c10-4 18 4 16 12-4-2-10-2-14 2z" fill="{STONE_L}"/><rect x="6" y="48" width="26" height="9" rx="3" fill="{WOOD_L}"/>'''
S["quarry"] = f'''<path d="M14 54L38 18" fill="none" stroke="{WOOD}" stroke-width="5"/><path d="M14 54L38 18" fill="none" stroke-width="1.4"/><path d="M22 14c10-8 26-4 32 6-10-2-18 0-24 6z" fill="{STONE}"/><path d="M8 58l12-8 8 8z" fill="{STONE_L}"/>'''
S["iron_mine"] = f'''<path d="M4 56V34c0-14 10-22 28-22s28 8 28 22v22z" fill="{STONE}"/><path d="M16 56V38c0-8 6-12 16-12s16 4 16 12v18z" fill="#4b3a2a"/><path d="M12 56h40" fill="none"/><rect x="24" y="44" width="16" height="9" rx="2" fill="{IRON}"/><circle cx="28" cy="55" r="3" fill="{IRON_L}"/><circle cx="38" cy="55" r="3" fill="{IRON_L}"/>'''
S["farm"] = f'''<path d="M4 44l28-14 28 14v12H4z" fill="{GREEN_L}"/><path d="M12 50l20-10 20 10M10 56l22-11 22 11" fill="none" stroke-width="1.6"/><circle cx="48" cy="16" r="7" fill="{GOLD_L}"/><path d="M32 40V22M26 26l6-8 6 8" fill="none" stroke="{GOLD}" stroke-width="3"/>'''
# ---- fixed
S["town_hall"] = f'''<path d="M6 30L32 12l26 18z" fill="{RED}"/><rect x="10" y="30" width="44" height="26" fill="{CREAM}"/><rect x="28" y="40" width="9" height="16" rx="4" fill="{WOOD}"/><rect x="14" y="36" width="8" height="10" fill="{IRON_L}"/><rect x="42" y="36" width="8" height="10" fill="{IRON_L}"/><path d="M32 12V4l9 3-9 3" fill="{GOLD}"/>'''
S["rally_point"] = f'''<path d="M18 58V8" fill="none" stroke="{WOOD}" stroke-width="5"/><path d="M18 58V8" fill="none" stroke-width="1.4"/><path d="M20 10h30l-8 10 8 10H20z" fill="{RED}"/><circle cx="30" cy="20" r="4" fill="{GOLD_L}"/><path d="M8 58h22" fill="none"/>'''
S["wall"] = f'''<path d="M4 56V22h8v6h8v-6h8v6h8v-6h8v6h8v-6h8v34z" fill="{STONE}"/><path d="M4 40h56M18 28v12M34 28v12M50 28v12M11 40v16M27 40v16M43 40v16M57 40v16" fill="none" stroke-width="1.4"/>'''
# ---- center
S["warehouse"] = f'''<path d="M4 28L32 8l28 20v28H4z" fill="{WOOD_L}"/><path d="M4 28L32 8l28 20" fill="none"/><rect x="14" y="34" width="36" height="22" fill="{WOOD}"/><path d="M14 45h36M32 34v22M14 34l36 22M50 34L14 56" fill="none" stroke-width="1.6"/>'''
S["granary"] = f'''<path d="M14 24c0-10 8-16 18-16s18 6 18 16z" fill="{RED}"/><rect x="14" y="24" width="36" height="32" fill="{GOLD_L}"/><path d="M14 34h36M14 44h36" fill="none" stroke-width="1.4"/><rect x="27" y="44" width="10" height="12" rx="5" fill="{WOOD}"/><path d="M32 8V3" fill="none"/>'''
S["barracks"] = f'''<path d="M4 56L32 8l28 48z" fill="{GREEN}"/><path d="M32 8v48" fill="none" stroke-width="1.6"/><path d="M24 56l8-18 8 18z" fill="#4b3a2a"/><path d="M32 8V2l9 3-9 3" fill="{RED}"/><path d="M8 56h48" fill="none"/>'''
S["smithy"] = f'''<path d="M8 26h40c6 0 8 4 8 8H44l-4 8H24l-4-8H8z" fill="{IRON}"/><rect x="22" y="42" width="20" height="14" rx="2" fill="{IRON_L}"/><path d="M14 26V20h14" fill="none"/><path d="M46 12l6 6M52 10l-4 4" fill="none" stroke="{GOLD}" stroke-width="3"/>'''
S["stable"] = f'''<path d="M4 30L32 12l28 18v26H4z" fill="{WOOD_L}"/><rect x="16" y="34" width="32" height="22" fill="{WOOD}"/><path d="M16 34l32 22M48 34L16 56" fill="none" stroke-width="1.6"/><path d="M26 22c4-6 12-6 14 0-2 2-4 2-6 0z" fill="{GOLD_L}"/>'''
S["workshop"] = f'''<circle cx="32" cy="32" r="14" fill="{IRON}"/><circle cx="32" cy="32" r="6" fill="{CREAM}"/><g fill="{IRON_L}"><rect x="28" y="6" width="8" height="12"/><rect x="28" y="46" width="8" height="12"/><rect x="6" y="28" width="12" height="8"/><rect x="46" y="28" width="12" height="8"/></g>'''
S["hideout"] = f'''<path d="M4 56c0-26 14-40 28-40s28 14 28 40z" fill="{GREEN}"/><path d="M20 56c0-12 6-18 12-18s12 6 12 18z" fill="#4b3a2a"/><rect x="26" y="44" width="12" height="10" rx="2" fill="{GOLD}"/><path d="M29 44v-3a3 3 0 0 1 6 0v3" fill="none"/>'''
S["marketplace"] = f'''<path d="M6 24h52l-4-12H10z" fill="{RED}"/><path d="M6 24c0 6 8 6 8 0 0 6 9 6 9 0 0 6 9 6 9 0 0 6 9 6 9 0 0 6 9 6 9 0z" fill="{CREAM}"/><rect x="10" y="30" width="44" height="8" fill="{WOOD_L}"/><path d="M12 38v18M52 38v18" fill="none" stroke-width="3"/><circle cx="24" cy="30" r="3" fill="{GREEN_L}"/><circle cx="34" cy="30" r="3" fill="{RED_L}"/>'''
S["palace"] = f'''<path d="M4 56V28l8-6 8 6v28zM44 56V28l8-6 8 6v28z" fill="{CREAM}"/><path d="M16 56V30h32v26z" fill="{SAND}"/><path d="M16 30c0-12 7-20 16-20s16 8 16 20z" fill="{GOLD}"/><path d="M32 10V3" fill="none"/><rect x="27" y="40" width="10" height="16" rx="5" fill="{WOOD}"/>'''
S["monument"] = f'''<path d="M24 56L28 10l4-6 4 6 4 46z" fill="{STONE_L}"/><path d="M14 56h36v-6H14z" fill="{STONE}"/><path d="M32 22l2 4 4 1-3 3 1 4-4-2-4 2 1-4-3-3 4-1z" fill="{GOLD}" stroke-width="1.4"/><path d="M10 56h44" fill="none"/>'''
# ---- units
S["spearman"] = f'''<path d="M14 58L48 8" fill="none" stroke="{WOOD}" stroke-width="4"/><path d="M14 58L48 8" fill="none" stroke-width="1.4"/><path d="M44 4l14-2-8 12z" fill="{IRON_L}"/><path d="M8 40c0-10 8-14 14-14l8 24-10 6z" fill="{IRON}"/>'''
S["swordsman"] = f'''<path d="M46 6l8 8-26 26-8-8z" fill="{IRON_L}"/><path d="M18 34l12 12M14 46l-6 6M22 42l-6 6" fill="none" stroke="{WOOD}" stroke-width="4"/><circle cx="12" cy="52" r="4" fill="{GOLD}"/>'''
S["scout"] = f'''<path d="M4 32c8-14 20-20 28-20s20 6 28 20c-8 14-20 20-28 20S12 46 4 32z" fill="{CREAM}"/><circle cx="32" cy="32" r="12" fill="{GREEN}"/><circle cx="32" cy="32" r="5" fill="{INK}"/><circle cx="36" cy="28" r="2.5" fill="{CREAM}" stroke="none"/>'''
S["light_cavalry"] = f'''<path d="M14 54c-2-12 0-22 8-28l10-12 6 8 12 2 6 10-12 4-4 16z" fill="{WOOD_L}"/><path d="M38 24l4-6 6 2" fill="none"/><circle cx="42" cy="26" r="1.8" fill="{INK}"/><path d="M8 20L52 6" fill="none" stroke="{WOOD}" stroke-width="3"/><path d="M50 4l8-1-3 8z" fill="{IRON_L}"/>'''
S["heavy_cavalry"] = f'''<path d="M14 54c-2-12 0-22 8-28l10-12 6 8 12 2 6 10-12 4-4 16z" fill="{IRON}"/><path d="M22 28l16-4M20 38l18-4" fill="none" stroke="{IRON_L}" stroke-width="3"/><circle cx="42" cy="26" r="1.8" fill="{CREAM}" stroke="none"/><path d="M32 14l2-8 6 8z" fill="{RED}"/>'''
S["ram"] = f'''<path d="M6 34h36v10H6z" fill="{WOOD}"/><path d="M42 30l14 9-14 9z" fill="{IRON}"/><path d="M10 28h28v6H10z" fill="{WOOD_L}"/><circle cx="14" cy="50" r="6" fill="{WOOD_L}"/><circle cx="34" cy="50" r="6" fill="{WOOD_L}"/><path d="M14 50h.1M34 50h.1" fill="none" stroke-width="3"/>'''
S["catapult"] = f'''<path d="M6 52h40l-4-12H10z" fill="{WOOD}"/><path d="M16 40l22-30" fill="none" stroke="{WOOD_L}" stroke-width="5"/><path d="M16 40l22-30" fill="none" stroke-width="1.4"/><circle cx="40" cy="10" r="7" fill="{STONE}"/><circle cx="16" cy="54" r="5" fill="{WOOD_L}"/><circle cx="38" cy="54" r="5" fill="{WOOD_L}"/>'''
S["chief"] = f'''<path d="M6 46l-2-24 14 12 14-20 14 20 14-12-2 24z" fill="{GOLD}"/><rect x="6" y="46" width="52" height="8" rx="2" fill="{GOLD_L}"/><circle cx="32" cy="38" r="3" fill="{RED}"/><circle cx="16" cy="40" r="2" fill="{RED}"/><circle cx="48" cy="40" r="2" fill="{RED}"/>'''
S["settler"] = f'''<path d="M6 34h40l-4 14H10z" fill="{WOOD_L}"/><path d="M12 34c0-14 12-22 20-22s14 8 14 22z" fill="{CREAM}"/><path d="M20 34v-8M32 34V16M44 34v-8" fill="none" stroke-width="1.4"/><circle cx="16" cy="52" r="5" fill="{WOOD}"/><circle cx="38" cy="52" r="5" fill="{WOOD}"/><path d="M46 38l14-6" fill="none"/>'''
# ---- ui + terrain
S["sword"] = S["swordsman"]
S["village"] = f'''<path d="M4 34L32 12l28 22z" fill="{RED}"/><rect x="10" y="34" width="44" height="22" fill="{CREAM}"/><rect x="26" y="42" width="12" height="14" rx="5" fill="{WOOD}"/><path d="M44 20V10h8v14" fill="{STONE}"/>'''
S["center"] = f'''<path d="M32 4l24 12v16c0 14-10 24-24 28C18 56 8 46 8 32V16z" fill="{BLUE}"/><path d="M32 14l14 7v11c0 8-6 14-14 17-8-3-14-9-14-17V21z" fill="{GOLD_L}" stroke-width="1.6"/><path d="M32 22v20M24 32h16" fill="none" stroke-width="3"/>'''
S["map"] = f'''<path d="M4 14l16-6 24 6 16-6v40l-16 6-24-6-16 6z" fill="{CREAM}"/><path d="M20 8v40M44 14v40" fill="none" stroke-width="1.6"/><path d="M26 30l6-8 8 12" fill="none" stroke="{GREEN}" stroke-width="3"/><circle cx="12" cy="30" r="3" fill="{RED}"/>'''
S["scroll"] = f'''<path d="M14 8h38v44c0 4-3 6-6 6H18c-6 0-8-4-8-8V14c0-3 2-6 4-6z" fill="{CREAM}"/><path d="M14 8c-4 0-6 3-6 6s2 6 6 6h6" fill="none"/><path d="M24 22h22M24 32h22M24 42h14" fill="none" stroke-width="1.8"/><circle cx="46" cy="46" r="6" fill="{RED}"/>'''
S["trophy"] = f'''<path d="M18 8h28v18c0 10-6 16-14 16S18 36 18 26z" fill="{GOLD}"/><path d="M18 14H8c0 10 4 16 12 16M46 14h10c0 10-4 16-12 16" fill="none"/><rect x="28" y="42" width="8" height="8" fill="{GOLD_L}"/><rect x="18" y="50" width="28" height="8" rx="2" fill="{WOOD}"/><path d="M32 14l2 5 5 1-4 3 1 5-4-3-4 3 1-5-4-3 5-1z" fill="{GOLD_L}" stroke-width="1.2"/>'''
S["help"] = f'''<circle cx="32" cy="32" r="26" fill="{GOLD_L}"/><path d="M23 25c0-6 4-9 9-9s9 3 9 8c0 7-9 7-9 14" fill="none" stroke-width="4"/><circle cx="32" cy="48" r="2.5" fill="{INK}"/>'''
S["pause"] = f'''<rect x="14" y="10" width="14" height="44" rx="3" fill="{WOOD_L}"/><rect x="36" y="10" width="14" height="44" rx="3" fill="{WOOD_L}"/>'''
S["play"] = f'''<path d="M16 8l36 24-36 24z" fill="{GREEN_L}"/>'''
S["ruin"] = f'''<path d="M6 56V24h10v32M24 56V12h10v44M44 56V30h10v26" fill="{SAND}"/><path d="M4 56h56" fill="none"/><path d="M24 12l10 6M44 30l10-4" fill="none" stroke-width="1.6"/><path d="M12 56l-4 4h14zM38 58l12 0" fill="none"/>'''
S["oasis"] = f'''<ellipse cx="32" cy="50" rx="26" ry="9" fill="#7fb2d9"/><path d="M32 46V22" fill="none" stroke="{WOOD}" stroke-width="5"/><path d="M32 22c-6-10-18-8-24 0 8-2 16 0 24 0zM32 22c6-10 18-8 24 0-8-2-16 0-24 0zM32 22c-4-12-2-16 0-18 2 2 4 6 0 18z" fill="{GREEN}"/>'''
S["mountain"] = f'''<path d="M2 56L22 18l12 20 8-12 20 30z" fill="{STONE}"/><path d="M22 18l-6 12 6-4 4 6zM42 26l-4 8 4-2 4 4z" fill="{CREAM}" stroke-width="1.4"/>'''
S["lake"] = f'''<ellipse cx="32" cy="34" rx="28" ry="18" fill="#7fb2d9"/><path d="M14 30c4-4 8-4 12 0s8 4 12 0 8-4 12 0M18 40c4-3 7-3 10 0s7 3 10 0" fill="none" stroke="{CREAM}" stroke-width="2"/>'''

def symbol(name: str, body: str) -> str:
    return (
        f'<symbol id="i-{name}" viewBox="0 0 64 64">'
        f'<g stroke="{INK}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round">{body}</g></symbol>'
    )

out = ['<svg xmlns="http://www.w3.org/2000/svg" style="display:none">']
out += [symbol(n, b) for n, b in S.items()]
out.append("</svg>")
open("web/img/icons.svg", "w", encoding="utf-8").write("\n".join(out) + "\n")
print(len(S), "symbols")
