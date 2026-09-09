import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import re

# ==========================================
# 1. KONFIGURASI HALAMAN
# ==========================================
st.set_page_config(
    page_title="Dashboard Pemantauan Kondisi Jalan",
    page_icon="🚧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 2. KONFIGURASI GOOGLE SHEETS
# ==========================================
# Ganti dengan Spreadsheet ID milik Anda
# Contoh URL asli: https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit
SPREADSHEET_ID = "1idOGnx2ECSUm-qV0kHPP3KeEVcQoukbjTT8zv0IEe4k"
SHEET_NAME = "Sheet1"  # Sesuaikan dengan nama sheet/tab di Google Sheets

# Endpoint export CSV langsung dari Google Sheets
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"


# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def convert_drive_to_direct_url(url: str) -> str:
    """
    Mengubah Google Drive sharing link menjadi direct image link (lh3.googleusercontent.com).
    Pastikan folder Drive diset 'Anyone with the link can view'.
    """
    if pd.isna(url) or not isinstance(url, str):
        return ""
    
    # Ekstraksi ID dari berbagai format link Drive
    match = re.search(r'[-\w]{25,}', url)
    if match:
        file_id = match.group(0)
        return f"https://lh3.googleusercontent.com/d/{file_id}"
    return url


@st.cache_data(ttl=60)  # Auto-refresh cache tiap 60 detik
def load_data(url: str) -> pd.DataFrame:
    """Membaca dan membersihkan data dari Google Sheets via CSV."""
    try:
        df = pd.read_csv(url)
    except Exception as e:
        st.error(f"Gagal memuat data dari Google Sheets: {e}")
        return pd.DataFrame()

    # Normalisasi nama kolom (huruf kecil & hapus spasi berlebih)
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    # Pastikan tipe data latitude & longitude numerik
    for col in ['latitude', 'lat']:
        if col in df.columns:
            df['latitude'] = pd.to_numeric(df[col], errors='coerce')
            break
            
    for col in ['longitude', 'lng', 'long']:
        if col in df.columns:
            df['longitude'] = pd.to_numeric(df[col], errors='coerce')
            break

    # Bersihkan baris yang tidak memiliki koordinat valid
    if 'latitude' in df.columns and 'longitude' in df.columns:
        df = df.dropna(subset=['latitude', 'longitude'])
        df = df[(df['latitude'] != 0) & (df['longitude'] != 0)]
    
    # Cari kolom foto dan lakukan konversi link direct
    foto_candidates = [c for c in df.columns if 'foto' in c or 'image' in c or 'gambar' in c]
    if foto_candidates:
        col_foto = foto_candidates[0]
        df['foto_direct'] = df[col_foto].apply(convert_drive_to_direct_url)
    else:
        df['foto_direct'] = ""

    return df


# ==========================================
# 4. LOAD DATA
# ==========================================
df_raw = load_data(SHEET_CSV_URL)

if df_raw.empty:
    st.warning("⚠️ Data belum berhasil dimuat atau tabel masih kosong. Periksa izin sharing Sheet Anda.")
    st.info("💡 Pastikan Google Sheets diatur ke **'Anyone with the link can view'**.")
    st.stop()

# ==========================================
# 5. SIDEBAR: FILTER
# ==========================================
st.sidebar.title("🔍 Filter Laporan")

df_filtered = df_raw.copy()

# Filter Kategori (jika ada kolom kategori/jenis)
cat_col = next((c for c in ['kategori', 'jenis_kerusakan', 'jenis', 'tipe'] if c in df_filtered.columns), None)
if cat_col:
    unique_cats = df_filtered[cat_col].dropna().unique().tolist()
    selected_cats = st.sidebar.multiselect("Kategori Kerusakan", options=unique_cats, default=unique_cats)
    df_filtered = df_filtered[df_filtered[cat_col].isin(selected_cats)]

# Filter Status (jika ada kolom status)
status_col = next((c for c in ['status', 'kondisi'] if c in df_filtered.columns), None)
if status_col:
    unique_status = df_filtered[status_col].dropna().unique().tolist()
    selected_status = st.sidebar.multiselect("Status Penanganan", options=unique_status, default=unique_status)
    df_filtered = df_filtered[df_filtered[status_col].isin(selected_status)]

st.sidebar.divider()
if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# ==========================================
# 6. HEADER & KPI METRICS
# ==========================================
st.title("🚧 Dashboard Monitoring Kerusakan Jalan")
st.caption("Data terintegrasi secara real-time dari formulir pelaporan masyarakat")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Laporan Terverifikasi", f"{len(df_filtered):,}")

if status_col:
    unresolved = df_filtered[df_filtered[status_col].str.lower().str.contains('tunggu|belum|proses', na=False)]
    resolved = df_filtered[df_filtered[status_col].str.lower().str.contains('selesai|tuntas', na=False)]
    col2.metric("Perlu Ditangani", f"{len(unresolved):,}")
    col3.metric("Selesai Diperbaiki", f"{len(resolved):,}")
else:
    col2.metric("Titik Terpetakan", f"{len(df_filtered):,}")
    col3.metric("Wilayah Pantauan", "Aktif")

col4.metric("Data Terakhir Diambil", pd.Timestamp.now().strftime("%H:%M:%S WIB"))

st.divider()

# ==========================================
# 7. PETA SEBARAN (FOLIUM)
# ==========================================
st.subheader("🗺️ Peta Sebaran Titik Laporan")

if not df_filtered.empty and 'latitude' in df_filtered.columns and 'longitude' in df_filtered.columns:
    center_lat = df_filtered['latitude'].median()
    center_lng = df_filtered['longitude'].median()

    # Inisialisasi Peta
    m = folium.Map(
        location=[center_lat, center_lng],
        zoom_start=13,
        tiles="CartoDB positron"  # Tampilan peta modern dan bersih
    )

    # Tambahkan Google Hybrid / Satelit layer opsional
    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Satellite (Hybrid)"
    ).add_to(m)

    # Marker Clustering agar titik tidak bertumpuk jika padat
    marker_cluster = MarkerCluster(name="Kluster Kerusakan").add_to(m)

    for _, row in df_filtered.iterrows():
        lat = row['latitude']
        lng = row['longitude']
        kategori_val = str(row.get(cat_col, "Kerusakan Jalan")).title() if cat_col else "Laporan Jalan"
        status_val = str(row.get(status_col, "Baru")).title() if status_col else "Tercatat"
        deskripsi_val = str(row.get('deskripsi', row.get('keterangan', '-')))
        foto_url = row.get('foto_direct', '')

        # HTML Popup Card
        img_html = f"""<img src="{foto_url}" style="width:100%; max-height:160px; object-fit:cover; border-radius:6px; margin-top:6px;" onerror="this.style.display='none';">""" if foto_url else ""
        
        popup_content = f"""
        <div style="font-family: Arial, sans-serif; width: 230px; line-height: 1.4;">
            <span style="background-color: #e63946; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold;">
                {kategori_val}
            </span>
            <div style="margin-top: 6px; font-size: 13px; font-weight: bold; color: #1d3557;">
                Status: {status_val}
            </div>
            <p style="font-size: 12px; color: #333; margin: 6px 0;">{deskripsi_val}</p>
            {img_html}
            <div style="font-size: 10px; color: #888; margin-top: 6px;">
                📍 {lat:.5f}, {lng:.5f}
            </div>
        </div>
        """

        # Tentukan warna icon berdasarkan status
        icon_color = "red"
        if "selesai" in status_val.lower():
            icon_color = "green"
        elif "proses" in status_val.lower():
            icon_color = "orange"

        folium.Marker(
            location=[lat, lng],
            popup=folium.Popup(popup_content, max_width=260),
            tooltip=f"{kategori_val} ({status_val})",
            icon=folium.Icon(color=icon_color, icon="info-sign")
        ).add_to(marker_cluster)

    folium.LayerControl().add_to(m)

    # Render peta ke Streamlit
    st_folium(m, width="100%", height=550, returned_objects=[])
else:
    st.info("Tidak ada data titik lokasi yang cocok dengan filter saat ini.")

# ==========================================
# 8. TABEL DETAIL & GALERI FOTO
# ==========================================
st.divider()
tab_tabel, tab_galeri = st.tabs(["📋 Tabel Data Lengkap", "📸 Galeri Foto Bukti"])

with tab_tabel:
    cols_to_display = [c for c in df_filtered.columns if c not in ['foto_direct']]
    st.dataframe(df_filtered[cols_to_display], use_container_width=True)

with tab_galeri:
    valid_photos = df_filtered[df_filtered['foto_direct'] != ""]
    if not valid_photos.empty:
        # Tampilkan galeri dengan 4 kolom per baris
        photo_cols = st.columns(4)
        for idx, (_, row) in enumerate(valid_photos.iterrows()):
            with photo_cols[idx % 4]:
                judul = str(row.get(cat_col, "Laporan")).title() if cat_col else "Laporan"
                st.image(row['foto_direct'], caption=f"{judul} - {row['latitude']:.4f}, {row['longitude']:.4f}", use_container_width=True)
    else:
        st.write("Belum ada foto laporan yang tersedia.")