import bpy
import bmesh
import json
import math
from mathutils import Vector

# ============================================================
# Iran damage spikes map for Blender - revised
# Reads the uploaded GeoJSON properly and makes low-value bars
# visible so the nationwide spread does not disappear.
# ============================================================

# -----------------------------
# USER SETTINGS
# -----------------------------
DAMAGE_GEOJSON = r"/mnt/data/damage_clusters (2)(1).geojson"

# Map sizing
TARGET_MAP_WIDTH = 12.0
COUNTRY_THICKNESS = 0.09
BAR_WIDTH = 0.032
BAR_BOTTOM_GAP = 0.01

# Height scaling
# Many features are small (1-5), so a clipped power scale works better than raw log.
BAR_MIN_HEIGHT = 0.16
BAR_MAX_HEIGHT = 4.8
PERCENTILE_CAP = 97.0   # cap extreme values so the rest do not vanish
HEIGHT_EXPONENT = 0.55  # <1 boosts smaller values

# Optional width scaling (very subtle)
WIDTH_EXPONENT = 0.18
MAX_WIDTH_MULTIPLIER = 1.6

# Colours
COUNTRY_TOP_COLOR = (0.95, 0.95, 0.95, 1.0)
COUNTRY_SIDE_COLOR = (0.86, 0.86, 0.86, 1.0)
LOW_COLOR = (1.00, 0.83, 0.78, 1.0)
HIGH_COLOR = (0.93, 0.24, 0.05, 1.0)
WORLD_BG = (0.965, 0.965, 0.965, 1.0)

# Render setup
RENDER_ENGINE = 'CYCLES'   # or 'BLENDER_EEVEE'
USE_ORTHO_CAMERA = True
RES_X = 1800
RES_Y = 1200

# ------------------------------------------------------------
# Embedded Iran outline in lon/lat
# ------------------------------------------------------------
IRAN_OUTLINE_LONLAT = [
    (48.567971, 29.926778), (48.014568, 30.452457), (48.004698, 30.985137),
    (47.685286, 30.984853), (47.849204, 31.709176), (47.334661, 32.469155),
    (46.109362, 33.017287), (45.416691, 33.967798), (45.648460, 34.748138),
    (46.151788, 35.093259), (46.076340, 35.677383), (45.420618, 35.977546),
    (44.772677, 37.170437), (44.225756, 37.971584), (44.421403, 38.281281),
    (44.109225, 39.428136), (44.793990, 39.713003), (44.952688, 39.335765),
    (45.457722, 38.874139), (46.143623, 38.741201), (46.505720, 38.770605),
    (47.685079, 39.508364), (48.060095, 39.582235), (48.355529, 39.288765),
    (48.010744, 38.794015), (48.634375, 38.270378), (48.883249, 38.320245),
    (49.199612, 37.582874), (50.147771, 37.374567), (50.842354, 36.872814),
    (52.264025, 36.700422), (53.825790, 36.965031), (53.921598, 37.198918),
    (54.800304, 37.392421), (55.511578, 37.964117), (56.180375, 37.935127),
    (56.619366, 38.121394), (57.330434, 38.029229), (58.436154, 37.522309),
    (59.234762, 37.412988), (60.377638, 36.527383), (61.123071, 36.491597),
    (61.210817, 35.650072), (60.803193, 34.404102), (60.528430, 33.676446),
    (60.963700, 33.528832), (60.536078, 32.981269), (60.863655, 32.182920),
    (60.941945, 31.548075), (61.699314, 31.379506), (61.781222, 30.735850),
    (60.874248, 29.829239), (61.369309, 29.303276), (61.771868, 28.699334),
    (62.727830, 28.259645), (62.755426, 27.378923), (63.233898, 27.217047),
    (63.316632, 26.756532), (61.874187, 26.239975), (61.497363, 25.078237),
    (59.616134, 25.380157), (58.525761, 25.609962), (57.397251, 25.739902),
    (56.970766, 26.966106), (56.492139, 27.143305), (55.723710, 26.964633),
    (54.715090, 26.480658), (53.493097, 26.812369), (52.483598, 27.580849),
    (51.520763, 27.865690), (50.852948, 28.814521), (50.115009, 30.147773),
    (49.576850, 29.985715), (48.941333, 30.317090), (48.567971, 29.926778)
]

# Equirectangular projection around Iran centre
LON0 = 54.0
LAT0 = 32.5
COS_LAT0 = math.cos(math.radians(LAT0))


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for data_block in (bpy.data.meshes, bpy.data.materials, bpy.data.curves, bpy.data.cameras, bpy.data.lights):
        for block in list(data_block):
            if block.users == 0:
                data_block.remove(block)


def project_lonlat(lon, lat):
    x = (lon - LON0) * COS_LAT0
    y = (lat - LAT0)
    return x, y


def bounds_2d(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def normalize_ring(ring):
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    out = []
    for p in ring:
        out.append((float(p[0]), float(p[1])))
    return out


def polygon_signed_area(coords):
    area = 0.0
    n = len(coords)
    for i in range(n):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area * 0.5


def polygon_centroid(coords):
    a = polygon_signed_area(coords)
    if abs(a) < 1e-12:
        xs = [p[0] for p in coords]
        ys = [p[1] for p in coords]
        return sum(xs) / len(xs), sum(ys) / len(ys)

    cx = 0.0
    cy = 0.0
    n = len(coords)
    for i in range(n):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    cx /= (6.0 * a)
    cy /= (6.0 * a)
    return cx, cy


def largest_outer_ring(geometry):
    gtype = geometry.get('type')
    coords = geometry.get('coordinates')

    if gtype == 'Polygon':
        return normalize_ring(coords[0])

    if gtype == 'MultiPolygon':
        best = None
        best_area = -1.0
        for poly in coords:
            ring = normalize_ring(poly[0])
            area = abs(polygon_signed_area(ring))
            if area > best_area:
                best_area = area
                best = ring
        return best

    raise ValueError(f'Unsupported geometry type: {gtype}')


def percentile(sorted_vals, pct):
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return d0 + d1


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_color(c1, c2, t):
    return (
        lerp(c1[0], c2[0], t),
        lerp(c1[1], c2[1], t),
        lerp(c1[2], c2[2], t),
        lerp(c1[3], c2[3], t),
    )


def make_principled_material(name, rgba, roughness=0.4, metallic=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new('ShaderNodeOutputMaterial')
    out.location = (250, 0)

    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)
    bsdf.inputs['Base Color'].default_value = rgba
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metallic

    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return mat


def make_object_color_material(name, roughness=0.28, emission_strength=0.08):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new('ShaderNodeOutputMaterial')
    out.location = (520, 0)

    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (220, 60)
    bsdf.inputs['Roughness'].default_value = roughness

    obj_info = nodes.new('ShaderNodeObjectInfo')
    obj_info.location = (-30, 110)

    emission = nodes.new('ShaderNodeEmission')
    emission.location = (220, -110)
    emission.inputs['Strength'].default_value = emission_strength

    add = nodes.new('ShaderNodeAddShader')
    add.location = (390, 0)

    links.new(obj_info.outputs['Color'], bsdf.inputs['Base Color'])
    links.new(obj_info.outputs['Color'], emission.inputs['Color'])
    links.new(bsdf.outputs['BSDF'], add.inputs[0])
    links.new(emission.outputs['Emission'], add.inputs[1])
    links.new(add.outputs['Shader'], out.inputs['Surface'])
    return mat


def create_country_mesh(projected_outline, thickness, top_mat, side_mat):
    mesh = bpy.data.meshes.new('IranBaseMesh')
    obj = bpy.data.objects.new('Iran_Base', mesh)
    bpy.context.collection.objects.link(obj)

    verts = [(x, y, 0.0) for x, y in projected_outline]
    faces = [list(range(len(verts)))]
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    top_faces = [f for f in bm.faces if f.normal.z >= 0]
    geom = bmesh.ops.extrude_face_region(bm, geom=top_faces)
    verts_extruded = [ele for ele in geom['geom'] if isinstance(ele, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=verts_extruded, vec=(0.0, 0.0, -thickness))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    obj.data.materials.append(top_mat)
    obj.data.materials.append(side_mat)
    for poly in obj.data.polygons:
        poly.material_index = 0 if poly.normal.z > 0.99 else 1
    return obj


def create_bar(name, x, y, z_bottom, width, height, material, color_rgba):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, z_bottom + height * 0.5))
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (width * 0.5, width * 0.5, height * 0.5)
    obj.data.materials.append(material)
    obj.color = color_rgba
    return obj


def look_at(obj, target):
    direction = Vector(target) - obj.location
    rot_quat = direction.to_track_quat('-Z', 'Y')
    obj.rotation_euler = rot_quat.to_euler()


def setup_world_and_camera(minx, miny, maxx, maxy, max_bar_height):
    scene = bpy.context.scene
    scene.render.engine = RENDER_ENGINE
    scene.render.resolution_x = RES_X
    scene.render.resolution_y = RES_Y
    scene.render.film_transparent = False

    world = scene.world or bpy.data.worlds.new('World')
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get('Background')
    if bg:
        bg.inputs[0].default_value = WORLD_BG
        bg.inputs[1].default_value = 1.0

    cx = (minx + maxx) * 0.5
    cy = (miny + maxy) * 0.5
    span_x = maxx - minx
    span_y = maxy - miny
    span = max(span_x, span_y)

    cam_data = bpy.data.cameras.new('Camera')
    cam_obj = bpy.data.objects.new('Camera', cam_data)
    bpy.context.collection.objects.link(cam_obj)
    scene.camera = cam_obj

    if USE_ORTHO_CAMERA:
        cam_data.type = 'ORTHO'
        cam_data.ortho_scale = span * 1.12
        cam_obj.location = Vector((cx + span * 0.10, cy - span * 1.18, span * 0.92 + max_bar_height * 0.35))
    else:
        cam_data.type = 'PERSP'
        cam_data.lens = 58
        cam_obj.location = Vector((cx + span * 0.10, cy - span * 1.25, span * 0.95 + max_bar_height * 0.35))
    look_at(cam_obj, (cx, cy, max_bar_height * 0.22))

    sun_data = bpy.data.lights.new(name='Sun', type='SUN')
    sun_data.energy = 3.0
    sun_obj = bpy.data.objects.new(name='Sun', object_data=sun_data)
    bpy.context.collection.objects.link(sun_obj)
    sun_obj.location = (cx - span, cy - span, span * 2.0)
    sun_obj.rotation_euler = (math.radians(48), 0, math.radians(-28))

    area_data = bpy.data.lights.new(name='Area', type='AREA')
    area_data.energy = 2800
    area_data.shape = 'RECTANGLE'
    area_data.size = span * 1.2
    area_data.size_y = span * 1.0
    area_obj = bpy.data.objects.new(name='Area', object_data=area_data)
    bpy.context.collection.objects.link(area_obj)
    area_obj.location = (cx + span * 0.15, cy - span * 0.50, span * 1.10)
    look_at(area_obj, (cx, cy, 0.2))


def main():
    clear_scene()

    with open(DAMAGE_GEOJSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    features = data.get('features', [])
    if not features:
        raise RuntimeError('No features found in GeoJSON.')

    # Project and center country outline
    outline_proj = [project_lonlat(lon, lat) for lon, lat in IRAN_OUTLINE_LONLAT]
    minx, miny, maxx, maxy = bounds_2d(outline_proj)
    scale = TARGET_MAP_WIDTH / (maxx - minx)

    outline_scaled = [(x * scale, y * scale) for x, y in outline_proj]
    ominx, ominy, omaxx, omaxy = bounds_2d(outline_scaled)
    center_x = (ominx + omaxx) * 0.5
    center_y = (ominy + omaxy) * 0.5
    outline_scaled = [(x - center_x, y - center_y) for x, y in outline_scaled]

    # Materials
    top_mat = make_principled_material('IranTop', COUNTRY_TOP_COLOR, roughness=0.48)
    side_mat = make_principled_material('IranSide', COUNTRY_SIDE_COLOR, roughness=0.60)
    bars_mat = make_object_color_material('Bars', roughness=0.26, emission_strength=0.10)

    country = create_country_mesh(outline_scaled, COUNTRY_THICKNESS, top_mat, side_mat)
    country.modifiers.new(name='Bevel', type='BEVEL').width = 0.012

    # Read every feature and convert each polygon centroid into a spike
    rows = []
    values = []
    for i, feat in enumerate(features):
        props = feat.get('properties', {})
        geom = feat.get('geometry')
        val = props.get('buildings_damaged', 0)

        try:
            val = float(val)
        except Exception:
            continue

        if val <= 0 or geom is None:
            continue

        ring = largest_outer_ring(geom)
        if not ring:
            continue
        lon, lat = polygon_centroid(ring)
        px, py = project_lonlat(lon, lat)
        sx = px * scale - center_x
        sy = py * scale - center_y
        rows.append((i, val, sx, sy))
        values.append(val)

    if not rows:
        raise RuntimeError('No usable buildings_damaged features found.')

    values_sorted = sorted(values)
    cap_val = percentile(values_sorted, PERCENTILE_CAP)
    if cap_val <= 0:
        cap_val = max(values_sorted)
    max_val = max(values_sorted)

    print(f'Loaded {len(rows)} spikes.')
    print(f'buildings_damaged min={min(values_sorted)} max={max_val} cap@{PERCENTILE_CAP}%={cap_val}')

    z0 = COUNTRY_THICKNESS + BAR_BOTTOM_GAP
    max_bar_height = 0.0

    # Draw small to large so tall bars sit visually on top
    rows.sort(key=lambda r: r[1])

    for idx, val, sx, sy in rows:
        capped = min(val, cap_val)
        t = (capped / cap_val) ** HEIGHT_EXPONENT if cap_val > 0 else 0.0
        t = max(0.0, min(1.0, t))

        height = lerp(BAR_MIN_HEIGHT, BAR_MAX_HEIGHT, t)
        width_t = (capped / cap_val) ** WIDTH_EXPONENT if cap_val > 0 else 0.0
        width = BAR_WIDTH * lerp(1.0, MAX_WIDTH_MULTIPLIER, width_t)
        color = lerp_color(LOW_COLOR, HIGH_COLOR, t)

        create_bar(
            name=f'bar_{idx:04d}',
            x=sx,
            y=sy,
            z_bottom=z0,
            width=width,
            height=height,
            material=bars_mat,
            color_rgba=color,
        )
        max_bar_height = max(max_bar_height, height)

    minx2, miny2, maxx2, maxy2 = bounds_2d(outline_scaled)
    setup_world_and_camera(minx2, miny2, maxx2, maxy2, max_bar_height)

    scene = bpy.context.scene
    if RENDER_ENGINE == 'CYCLES':
        scene.cycles.samples = 128

    print('Done: revised Iran spike map created.')


if __name__ == '__main__':
    main()
