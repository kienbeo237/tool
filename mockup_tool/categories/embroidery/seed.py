"""Bộ quy tắc khởi tạo cho danh mục áo thêu.

QUAN TRỌNG: đây là bản dựng lại từ các cụm từ khoá trích trong tài liệu thiết kế.
Cần thay bằng NGUYÊN VĂN bộ quy tắc và các prompt khách đã duyệt (trong file
conversation của khách) qua tab "Quy tắc" — mỗi lần lưu tạo một phiên bản mới.
Mã hex màu áo là giá trị gần đúng, cần khách xác nhận.
"""

BLOCKS = {
    # ---- Chỉ dẫn gửi cho model (không xuất hiện trong prompt cuối) ----
    "design_instruction": (
        "You are a senior embroidery designer creating apparel embroidery for a print-on-demand shop. "
        "The customer's images are IDEA REFERENCES ONLY, not finished artwork: take the concept and the "
        "wording of any text, then completely redesign the artwork with your own original shapes, "
        "composition and details so it is clearly not a copy of the reference. Never copy the reference "
        "background either. Simplify everything for machine embroidery: bold clean shapes, solid color "
        "fills, 2-5 thread colors, no gradients, no shading, no photo-realistic detail, no thick black "
        "outlines. When two idea images are given, merge both ideas into one cohesive design (for example "
        "a goose wearing firefighter gear). Keep the design charming, cozy and boutique-quality, and "
        "readable at a small pocket size."
    ),
    "scene_instruction": (
        "Describe the background setting of this photo so it can be recreated as the backdrop for a new "
        "garment mockup. Describe only the surface, props, lighting, camera angle, how the item is "
        "arranged, the scene colors and the composition. Ignore and never describe any garment, artwork, "
        "logo or text in the photo."
    ),
    # ---- Mặc định phong cách (bậc ưu tiên thấp nhất, mục 6.2) ----
    "default_camera": "A top-down flat lay product photograph shot straight from above",
    "default_lighting": "soft natural daylight with gentle, diffused soft shadows",
    "default_arrangement": "neatly folded",
    # ---- Đoạn 1: góc máy + áo + bề mặt + đạo cụ + ánh sáng ----
    "para1": (
        "{camera} of a {arrangement} {color} {garment} {surface}. {props} "
        "The scene is lit by {lighting}. {extra} "
        "The composition is framed for a {aspect_ratio} aspect ratio."
    ),
    # ---- Đoạn 2: chất liệu + khung hình + kéo căng vải ----
    "para2": (
        "The {garment} is made of {material} in a rich {color_name} tone with a subtle, realistic fabric "
        "texture, framed so the full chest area is clearly visible and centered in the frame. {puckering}"
    ),
    "puckering": (
        "The fabric shows authentic physical puckering and subtle radial micro-creases around the perimeter "
        "of the embroidery, with distinct concave fabric indentations where tight machine thread tension "
        "physically pulls and cinches into the plush fleece material."
    ),
    # ---- Đoạn 3: dòng mở đầu ép tỷ lệ + gạch đầu dòng (model sinh) + Palette & Style ----
    "para3_intro": (
        "The embroidered design is a {motif}, rendered at a petite, compact, and dainty scale, occupying "
        "only a small area with expansive, generous plain negative space around it. {placement_clause}"
    ),
    "para3_palette": (
        "Palette & Style: {threads} thread only ({thread_count} colors), flat solid color fills, no "
        "gradients, no shading, no thick black outlines, simplified clean shapes optimized for machine "
        "embroidery."
    ),
    # ---- Đoạn 4: kỹ thuật mũi thêu + độ nổi + tổng kết ----
    "para4": (
        "Embroidery technique: {technique_sentences} {thread_physics} {anti_print} The overall look is a "
        "clean, minimal, premium boutique embroidered {garment}, captured as a realistic product mockup."
    ),
    "satin_sentence": "Smooth, glossy satin stitches are used for {parts}.",
    "tatami_sentence": "Dense tatami fill stitches cover {parts}.",
    "running_sentence": "Fine running stitches define {parts}.",
    "thread_physics": (
        "Stitched with high-density 40wt polyester embroidery thread with authentic silky sheen, forming "
        "tangible 3D thread relief standing 1-2mm raised above the fabric surface."
    ),
    "anti_print": (
        "The design is completely free of flat printed ink, DTG textures, or vector illustration "
        "appearance—100% genuine physical machine embroidery."
    ),
}

PRODUCT_TYPES = [
    {"key": "gildan_sweatshirt", "label": "Gildan 18000 Sweatshirt",
     "phrase": "Gildan 18000 crewneck sweatshirt", "material": "soft, heavyweight cotton-polyester fleece"},
    {"key": "gildan_hoodie", "label": "Gildan 18500 Hoodie",
     "phrase": "Gildan 18500 pullover hoodie", "material": "soft, heavyweight cotton-polyester fleece"},
    {"key": "comfort_colors_tee", "label": "Comfort Colors 1717 Tee",
     "phrase": "Comfort Colors 1717 garment-dyed t-shirt", "material": "thick, garment-dyed ring-spun cotton"},
    {"key": "gildan_tee", "label": "Gildan 5000 Tee",
     "phrase": "Gildan 5000 heavy cotton t-shirt", "material": "classic heavyweight cotton jersey"},
]

COLORS = [
    {"key": "forest_green", "label": "Forest Green", "hex": "#2c3f2e"},
    {"key": "maroon", "label": "Maroon", "hex": "#5b2333"},
    {"key": "sport_gray", "label": "Sport Gray", "hex": "#a3a3a3"},
    {"key": "sand", "label": "Sand", "hex": "#cbb999"},
    {"key": "white", "label": "White", "hex": "#ffffff"},
    {"key": "light_blue", "label": "Light Blue", "hex": "#a7c4e2"},
    {"key": "light_pink", "label": "Light Pink", "hex": "#f2c6d3"},
    {"key": "black", "label": "Black", "hex": "#1b1b1b"},
    {"key": "orange", "label": "Orange", "hex": "#f26b21"},
    {"key": "carolina_blue", "label": "Carolina Blue", "hex": "#7ba4db"},
    {"key": "chocolate_brown", "label": "Chocolate Brown", "hex": "#4a2f27"},
]

PLACEMENTS = [
    {"key": "center_chest", "label": "Center chest",
     "phrase": "It sits in a pocket-sized footprint centered on the chest, leaving a vast expanse of clean, "
               "plain {color_name} fabric around it so it does not look oversized."},
    {"key": "left_chest", "label": "Left chest",
     "phrase": "It is rendered at a small pocket-placement scale positioned strictly on the left chest area, "
               "leaving the rest of the {color_name} fabric clean and plain."},
]

# Sáu concept bề mặt chuẩn (mục 6.1). `surface` bắt đầu bằng giới từ để ghép thẳng sau tên áo.
BACKGROUNDS = [
    {"key": "wooden_table", "label": "Bàn gỗ",
     "surface": "laid flat on a warm rustic oak wooden table with visible natural grain",
     "props": "A small ceramic mug of coffee and a sprig of dried eucalyptus rest near the edges of the frame."},
    {"key": "grass", "label": "Thảm cỏ",
     "surface": "laid flat on a lush, freshly trimmed green lawn",
     "props": "A few scattered wildflowers sit near the corners of the frame."},
    {"key": "rock", "label": "Tảng đá",
     "surface": "laid flat on a large, flat natural granite rock with a weathered texture",
     "props": "Small smooth pebbles and a trace of soft moss sit at the edges of the frame."},
    {"key": "fur_rug", "label": "Thảm lông",
     "surface": "laid flat on a soft cream faux-fur shag rug",
     "props": "The corner of a chunky knit throw blanket peeks in at the edge of the frame."},
    {"key": "gingham_denim", "label": "Khăn gingham trên jeans",
     "surface": "laid on a red-and-white gingham cloth layered over a folded pair of blue denim jeans",
     "props": ""},
    {"key": "handheld_outdoor", "label": "Cầm tay ngoài trời",
     "camera": "A natural lifestyle product photograph",
     "arrangement": "neatly presented",
     "surface": "held up by one hand in front of a softly blurred outdoor park background with natural greenery",
     "props": ""},
]

ASPECT_RATIOS = ["1:1", "4:5", "3:4", "2:3", "9:16", "16:9"]


def seed_dict() -> dict:
    return {
        "product_types": PRODUCT_TYPES,
        "colors": COLORS,
        "placements": PLACEMENTS,
        "backgrounds": BACKGROUNDS,
        "aspect_ratios": ASPECT_RATIOS,
        "blocks": BLOCKS,
    }
