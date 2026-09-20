import pymupdf  # Modern import style (replacing 'import fitz')

doc = pymupdf.open()

# 1. Create a page (e.g., matching target pixel dimensions converted to points)
# Assuming 300 DPI: width_pts = width_px * 72 / 300
page = doc.new_page(width=565, height=993)

# 2. Add Layer (OCG) definitions to the document catalog
bg_ocg_id = doc.add_ocg("Original Paper Texture", on=True)
text_ocg_id = doc.add_ocg("Cleaned Text (High-Contrast)", on=True)

# 3. Insert background image onto its layer
page.insert_image(
    page.rect,
    filename="./matrix_test/page_216_stream-000.png",
    oc=bg_ocg_id,
)

# 4. Insert clean text image onto its layer
page.insert_image(
    page.rect,
    filename="./matrix_test/p9_pipe4_final.png",
    oc=text_ocg_id,
)

# Save with garbage collection to keep the file lean
doc.save("Hertz_1894_DualLayer.pdf", garbage=4, deflate=True)
