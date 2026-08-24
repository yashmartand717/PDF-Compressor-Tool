import streamlit as st
import pymupdf
import tempfile
import os
from PIL import Image
import io
import gc

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="PDF Compressor", page_icon="🗜️", layout="centered")

st.title("🗜️ PDF Compressor Tool")
st.markdown("Replicating commercial-grade compression by downsampling and re-encoding embedded textbook images.")

# --- SESSION STATE INITIALIZATION ---
if "compressed_data" not in st.session_state:
    st.session_state.compressed_data = None
if "original_filename" not in st.session_state:
    st.session_state.original_filename = ""
if "stats" not in st.session_state:
    st.session_state.stats = {}

uploaded_file = st.file_uploader("Upload a PDF file", type=["pdf"])

if uploaded_file is not None:
    if st.session_state.original_filename != uploaded_file.name:
        st.session_state.compressed_data = None
        st.session_state.original_filename = uploaded_file.name
        st.session_state.stats = {}

    original_size_mb = uploaded_file.size / (1024 * 1024)
    st.info(f"📄 **Original File Size:** {original_size_mb:.2f} MB")

    # --- iLOVEPDF-STYLE SETTINGS ---
    compression_level = st.radio(
        "Select Compression Level:",
        (
            "🟢 Recommended Compression (Good quality, high compression)", 
            "🔴 Extreme Compression (Lower quality, maximum compression)",
            "⚙️ Custom Settings"
        ),
        index=0
    )

    if "Recommended" in compression_level:
        max_image_dim = 1200
        jpeg_quality = 65
    elif "Extreme" in compression_level:
        max_image_dim = 800
        jpeg_quality = 40
    else:
        max_image_dim = st.slider("Max Image Resolution (Pixels)", 500, 3000, 1000, 100)
        jpeg_quality = st.slider("JPEG Quality (%)", 10, 100, 50, 5)

    if st.button("Compress PDF", type="primary", use_container_width=True):
        progress_bar = st.progress(5, text="Saving uploaded file to temporary disk...")
        
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_in:
                tmp_in.write(uploaded_file.getvalue())
                input_path = tmp_in.name
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_out:
                output_path = tmp_out.name

            doc = pymupdf.open(input_path)
            total_pages = len(doc)
            
            images_processed = 0
            
            # --- MEMORY-SAFE PIXMAP ENGINE ---
            for page_num in range(total_pages):
                progress_bar.progress(10 + int((page_num / total_pages) * 70), text=f"Downsampling images on page {page_num + 1}/{total_pages}...")
                
                page = doc[page_num]
                image_list = page.get_images()
                
                for img in image_list:
                    xref = img[0]
                    
                    try:
                        # 1. Use Pixmap instead of raw extraction (prevents RAM spikes on complex formats)
                        pix = pymupdf.Pixmap(doc, xref)
                        
                        # Skip tiny icons/masks to save processing time
                        if pix.width < 100 or pix.height < 100:
                            pix = None
                            continue
                            
                        # 2. Force conversion to RGB if it's CMYK or has Alpha
                        if pix.n > 3 or pix.alpha:
                            pix_rgb = pymupdf.Pixmap(pymupdf.csRGB, pix)
                            pix = None # Free old memory immediately
                            pix = pix_rgb
                        
                        # 3. Load cleanly into Pillow using raw bytes
                        pil_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        pix = None # Free C-level memory immediately
                        
                        # 4. Resize if too large
                        width, height = pil_img.size
                        if width > max_image_dim or height > max_image_dim:
                            ratio = min(max_image_dim / width, max_image_dim / height)
                            new_size = (int(width * ratio), int(height * ratio))
                            pil_img = pil_img.resize(new_size, Image.Resampling.BILINEAR)
                        
                        # 5. Save as compressed JPEG
                        new_bytes = io.BytesIO()
                        pil_img.save(new_bytes, format="JPEG", quality=jpeg_quality, optimize=True)
                        
                        # 6. Replace in PDF
                        page.replace_image(xref, stream=new_bytes.getvalue())
                        images_processed += 1
                        
                        # 7. EXPLICITLY free Python memory
                        pil_img.close()
                        del new_bytes
                        
                    except Exception as e:
                        print(f"Skipped image {xref}: {e}")
                        continue 
                
                # Force garbage collection at the end of every page
                gc.collect()
            
            progress_bar.progress(85, text="Compacting final PDF structure (this takes a moment)...")
            
            doc.save(
                output_path,
                garbage=4, 
                deflate=True, 
                clean=True,
                use_objstms=True
            )
            doc.close()
            
            progress_bar.progress(95, text="Preparing your download...")
            
            with open(output_path, "rb") as f:
                compressed_bytes = f.read()
                
            compressed_size_mb = len(compressed_bytes) / (1024 * 1024)
            savings_pct = (1 - (len(compressed_bytes) / uploaded_file.size)) * 100

            os.remove(input_path)
            os.remove(output_path)

            st.session_state.compressed_data = compressed_bytes
            st.session_state.stats = {
                "compressed_mb": compressed_size_mb,
                "savings_pct": savings_pct,
                "saved_mb": original_size_mb - compressed_size_mb,
                "images_processed": images_processed
            }
            
            progress_bar.empty()
            if images_processed == 0:
                st.warning("⚠️ No standard images were found to compress. The PDF might be made of complex vector paths.")
            else:
                st.success(f"✅ Compression complete! Successfully downsampled {images_processed} images.")

        except Exception as e:
            progress_bar.empty()
            st.error(f"❌ Error during compression: {e}")

# --- PERSISTENT RESULTS & DOWNLOAD ---
if st.session_state.compressed_data is not None:
    stats = st.session_state.stats
    st.divider()
    
    col1, col2 = st.columns(2)
    col1.metric("New Size", f"{stats['compressed_mb']:.2f} MB", f"{-stats['savings_pct']:.1f}%")
    col2.metric("Space Saved", f"{stats['saved_mb']:.2f} MB")

    st.download_button(
        label="📥 Download Compressed PDF",
        data=st.session_state.compressed_data,
        file_name=f"compressed_{st.session_state.original_filename}",
        mime="application/pdf",
        use_container_width=True
    )