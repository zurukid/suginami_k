#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_map_v2.py  –  Run with Python 3.9 (/Library/Developer/CommandLineTools/usr/bin/python3)
Requires: shapely 2.x (already installed for that Python)

Fetches 杉並区 town boundaries → merges per region via unary_union
→ outputs SVG <path> elements with accurate geography.
"""

import json, urllib.request, urllib.parse, ssl, re, sys
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

# ── Region assignments ────────────────────────────────────────────────────
REGION_MAP = {
    '下井草':'ikusa','井草':'ikusa','上井草':'ikusa',
    '西荻北':'nishiogi','西荻南':'nishiogi','松庵':'nishiogi',
    '善福寺':'nishiogi','宮前':'nishiogi',
    '上荻':'nishiogi','桃井':'nishiogi',
    '荻窪':'ogikubo','今川':'ogikubo',
    '清水':'ogikubo','南荻窪':'ogikubo',
    '天沼':'ogikubo','本天沼':'ogikubo',
    '阿佐谷北':'asagaya','阿佐谷南':'asagaya',
    '成田東':'asagaya','成田西':'asagaya',
    '高円寺北':'koenji','高円寺南':'koenji',
    '梅里':'koenji','和田':'koenji','堀ノ内':'koenji','松ノ木':'koenji',
    '高井戸東':'takaido','高井戸西':'takaido',
    '上高井戸':'takaido','下高井戸':'takaido','久我山':'takaido','浜田山':'takaido',
    '方南':'honan','和泉':'honan','永福':'honan','大宮':'honan',
}

REGION_COLORS = {
    'ikusa':'#5C8DBF','nishiogi':'#47917F','ogikubo':'#C8873A',
    'asagaya':'#6AA54E','koenji':'#8B4FA8','takaido':'#457CA0','honan':'#B55870',
}

# ── Projection ────────────────────────────────────────────────────────────
SVG_W, SVG_H = 480, 476
PAD = 8
LON_MIN, LON_MAX = 139.585, 139.672
LAT_MIN, LAT_MAX = 35.663, 35.733
# SVG_H=476 gives cos(35.7°)-corrected proportions for geographic accuracy

def proj(lon, lat):
    x = PAD + (lon - LON_MIN) / (LON_MAX - LON_MIN) * (SVG_W - 2 * PAD)
    y = PAD + (LAT_MAX - lat) / (LAT_MAX - LAT_MIN) * (SVG_H - 2 * PAD)
    return (x, y)

def unproj(x, y):
    lon = LON_MIN + (x - PAD) / (SVG_W - 2 * PAD) * (LON_MAX - LON_MIN)
    lat = LAT_MAX - (y - PAD) / (SVG_H - 2 * PAD) * (LAT_MAX - LAT_MIN)
    return (lon, lat)

# ── Helpers ───────────────────────────────────────────────────────────────
def base_town(name):
    return re.sub(r'[〇一二三四五六七八九十百]+丁目$', '', name)

def get_region(name):
    return REGION_MAP.get(base_town(name))

def pdist(a, b):
    return ((a[0]-b[0])**2 + (a[1]-b[1])**2)**0.5

def pld(p, a, b):
    ax,ay=a; bx,by=b; px_,py_=p
    dx,dy=bx-ax,by-ay
    if dx==0 and dy==0: return pdist(p,a)
    t = max(0, min(1, ((px_-ax)*dx+(py_-ay)*dy)/(dx*dx+dy*dy)))
    return pdist(p,(ax+t*dx,ay+t*dy))

def rdp(pts, eps):
    if len(pts) < 3: return pts
    md,idx=0,0
    for i in range(1,len(pts)-1):
        d=pld(pts[i],pts[0],pts[-1])
        if d>md: md,idx=d,i
    if md>=eps: return rdp(pts[:idx+1],eps)[:-1]+rdp(pts[idx:],eps)
    return [pts[0],pts[-1]]

# ── OSM fetch ─────────────────────────────────────────────────────────────
def fetch_overpass(query):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = 'https://overpass-api.de/api/interpreter'
    d = urllib.parse.urlencode({'data': query}).encode()
    req = urllib.request.Request(url, data=d, headers={'User-Agent': 'suginami-k/2.0'})
    print("Fetching from Overpass...", file=sys.stderr)
    with urllib.request.urlopen(req, timeout=120, context=ctx) as r:
        return json.load(r)

# ── Ring building ─────────────────────────────────────────────────────────
def build_rings(ways):
    if not ways: return []
    segs = [list(w) for w in ways if len(w) >= 2]
    rings = []
    while segs:
        ring = list(segs.pop(0))
        changed = True
        while changed:
            changed = False
            s = ring[0]; e = ring[-1]
            sp = proj(s[0],s[1]); ep = proj(e[0],e[1])
            if pdist(sp,ep) < 1.5: break
            for i, seg in enumerate(segs):
                a = proj(seg[0][0],seg[0][1])
                b = proj(seg[-1][0],seg[-1][1])
                if pdist(ep,a)<1.5:   ring.extend(seg[1:]); segs.pop(i); changed=True; break
                elif pdist(ep,b)<1.5: ring.extend(list(reversed(seg))[1:]); segs.pop(i); changed=True; break
                elif pdist(sp,b)<1.5: ring=seg+ring[1:]; segs.pop(i); changed=True; break
                elif pdist(sp,a)<1.5: ring=list(reversed(seg))+ring[1:]; segs.pop(i); changed=True; break
        rings.append(ring)
    return rings

def relation_to_shapely(el):
    """Convert OSM relation to shapely (Multi)Polygon in projected coordinates."""
    members = el.get('members', [])
    outer_ways, inner_ways = [], []
    for m in members:
        if m.get('type') != 'way' or not m.get('geometry'): continue
        coords = [(c['lon'], c['lat']) for c in m['geometry']]
        (inner_ways if m.get('role')=='inner' else outer_ways).append(coords)

    outer_rings = build_rings(outer_ways)
    inner_rings = build_rings(inner_ways)

    polys = []
    for ring in outer_rings:
        px_ring = [proj(c[0],c[1]) for c in ring]
        if len(px_ring) < 3: continue
        # Find corresponding inner rings (holes)
        holes = []
        for h in inner_rings:
            ph = [proj(c[0],c[1]) for c in h]
            if len(ph) >= 3:
                holes.append(ph)
        try:
            p = Polygon(px_ring, holes)
            if p.is_valid and not p.is_empty:
                polys.append(p)
        except Exception:
            pass

    if not polys: return None
    try:
        result = unary_union(polys)
        return result if not result.is_empty else None
    except Exception:
        return None

def shapely_to_svg(geom, eps=0.5):
    """Convert shapely geometry to SVG path d-string."""
    def ring_to_d(coords):
        simp = rdp(list(coords), eps)
        if len(simp) < 3: simp = list(coords)
        return 'M' + 'L'.join(f"{round(p[0],1)},{round(p[1],1)}" for p in simp) + 'Z'

    parts = []
    if geom.geom_type == 'Polygon':
        parts.append(ring_to_d(geom.exterior.coords))
        for interior in geom.interiors:
            parts.append(ring_to_d(interior.coords))
    elif geom.geom_type == 'MultiPolygon':
        for poly in geom.geoms:
            if poly.area < 8: continue  # drop tiny merge slivers
            parts.append(ring_to_d(poly.exterior.coords))
            for interior in poly.interiors:
                parts.append(ring_to_d(interior.coords))
    return ' '.join(parts)

# ── Train line path ───────────────────────────────────────────────────────
def line_path(waypoints):
    pts = [proj(lon, lat) for lon, lat in waypoints]
    return 'M' + 'L'.join(f"{round(p[0],1)},{round(p[1],1)}" for p in pts)

# ── Station data (OSM-verified coordinates) ───────────────────────────────
# (name, lon, lat, stroke_color, label_dy)
STATIONS = [
    # JR中央線
    ('西荻窪',   139.5996, 35.7037, '#E65C14', -8),
    ('荻窪',     139.6200, 35.7043, '#E65C14', -8),
    ('阿佐ヶ谷',  139.6355, 35.7048, '#E65C14', -8),
    ('高円寺',   139.6500, 35.7055, '#E65C14', -8),
    # 西武新宿線 (東→西 順: 下井草→井荻→上井草)
    ('下井草',   139.6253, 35.7238, '#1458C8', +12),
    ('井荻',     139.6152, 35.7247, '#1458C8', -8),
    ('上井草',   139.6031, 35.7253, '#1458C8', +12),
    # 京王井の頭線
    ('久我山',    139.5996, 35.6880, '#2A9D8A', -8),
    ('富士見ヶ丘', 139.6076, 35.6847, '#2A9D8A', +13),
    ('高井戸',    139.6149, 35.6832, '#2A9D8A', -8),
    ('浜田山',    139.6275, 35.6816, '#2A9D8A', +13),
    ('西永福',    139.6355, 35.6787, '#2A9D8A', -8),
    ('永福町',    139.6426, 35.6763, '#2A9D8A', +13),
]

# ── Train line routes built from station coordinates ─────────────────────
# JR中央線: 三鷹方面→西荻窪→荻窪→阿佐ヶ谷→高円寺→中野方面
CHUO_LINE = [
    (139.585,  35.7037),
    (139.5996, 35.7037),   # 西荻窪
    (139.6200, 35.7043),   # 荻窪
    (139.6355, 35.7048),   # 阿佐ヶ谷
    (139.6500, 35.7055),   # 高円寺
    (139.672,  35.7058),
]

# 西武新宿線: 中野区方面(東)→下井草→井荻→上井草→練馬区方面(西)
SEIBU_LINE = [
    (139.672,  35.7222),
    (139.6253, 35.7238),   # 下井草
    (139.6152, 35.7247),   # 井荻
    (139.6031, 35.7253),   # 上井草
    (139.585,  35.7262),
]

# 京王井の頭線: 三鷹方面(西)→久我山→富士見ヶ丘→高井戸→浜田山→西永福→永福町→渋谷方面(東)
KEIO_LINE = [
    (139.585,  35.6888),
    (139.5996, 35.6880),   # 久我山
    (139.6076, 35.6847),   # 富士見ヶ丘
    (139.6149, 35.6832),   # 高井戸
    (139.6275, 35.6816),   # 浜田山
    (139.6355, 35.6787),   # 西永福
    (139.6426, 35.6763),   # 永福町
    (139.672,  35.6730),
]

# ── Area labels ───────────────────────────────────────────────────────────
REGION_LABELS = {
    'ikusa':    (139.619, 35.722, '井草'),
    'nishiogi': (139.598, 35.696, '西荻'),
    'ogikubo':  (139.617, 35.708, '荻窪'),
    'asagaya':  (139.636, 35.699, '阿佐谷'),
    'koenji':   (139.658, 35.701, '高円寺'),
    'takaido':  (139.610, 35.675, '高井戸'),
    'honan':    (139.650, 35.679, '方南・\n和泉'),
}

# ── Main ──────────────────────────────────────────────────────────────────
def main():
    query = '''
[out:json][timeout:90];
area[name="杉並区"]["admin_level"="7"]->.suginami;
(
  relation["admin_level"="9"](area.suginami);
  relation["admin_level"="10"](area.suginami);
);
out geom;
'''
    data = fetch_overpass(query)
    elements = data.get('elements', [])
    print(f"Got {len(elements)} elements", file=sys.stderr)

    # Collect shapely polygons per region
    region_geoms = {r: [] for r in REGION_COLORS}
    unmatched = []

    for el in elements:
        if el.get('type') != 'relation': continue
        name = el.get('tags', {}).get('name', '')
        region = get_region(name)
        if not region:
            unmatched.append(name)
            continue
        g = relation_to_shapely(el)
        if g:
            region_geoms[region].append(g)

    if unmatched:
        print(f"Unmatched: {sorted(set(unmatched))}", file=sys.stderr)

    # Merge geometries per region
    print("Merging polygons per region...", file=sys.stderr)
    region_merged = {}
    for region, geoms in region_geoms.items():
        if not geoms:
            print(f"  WARNING: no geoms for {region}", file=sys.stderr)
            continue
        try:
            merged = unary_union(geoms)
            if not merged.is_empty:
                region_merged[region] = merged
                print(f"  {region}: merged {len(geoms)} polygons", file=sys.stderr)
        except Exception as e:
            print(f"  {region}: merge failed: {e}", file=sys.stderr)

    # Region boundaries follow official 町丁目 lines directly (no redistribution).
    # The 7地域 are defined as 町丁目 groupings, so the merged outlines ARE the
    # official 区民センター地域 boundaries.

    # Output SVG elements
    lines = []

    # Region paths (merged, clean outlines)
    for region, color in REGION_COLORS.items():
        if region not in region_merged:
            print(f"WARNING: {region} missing", file=sys.stderr)
            continue
        d = shapely_to_svg(region_merged[region], eps=1.2)
        lines.append(f'            <path class="area-region" data-area="{region}" fill="{color}" d="{d}"/>')

    # Train lines
    lines.append(f'            <path class="train-line train-chuo" d="{line_path(CHUO_LINE)}"/>')
    lines.append(f'            <path class="train-line train-seibu" d="{line_path(SEIBU_LINE)}"/>')
    lines.append(f'            <path class="train-line train-keio" d="{line_path(KEIO_LINE)}"/>')

    # Station markers
    for name, lon, lat, color, dy in STATIONS:
        x, y = proj(lon, lat)
        r = 3.5 if color == '#E65C14' else 3
        x_r = round(x,1); y_r = round(y,1)
        lines.append(f'            <circle cx="{x_r}" cy="{y_r}" r="{r}" fill="#fff" stroke="{color}" stroke-width="1.5"/>')
        lines.append(f'            <text x="{x_r}" y="{round(y+dy,1)}" class="station-label" text-anchor="middle">{name}</text>')

    # Area labels
    for region, (lon, lat, label) in REGION_LABELS.items():
        x, y = round(proj(lon,lat)[0],1), round(proj(lon,lat)[1],1)
        if '\n' in label:
            parts = label.split('\n')
            lines.append(f'            <text class="area-label area-label-sm" x="{x}" y="{y}" text-anchor="middle">{parts[0]}</text>')
            lines.append(f'            <text class="area-label area-label-sm" x="{x}" y="{round(y+13,1)}" text-anchor="middle">{parts[1]}</text>')
        else:
            lines.append(f'            <text class="area-label" x="{x}" y="{y}" text-anchor="middle">{label}</text>')

    print('\n'.join(lines))


if __name__ == '__main__':
    main()
