import os
import re
import shutil
import zipfile
import contextlib
import io
from flask import Flask, render_template, request, redirect, send_file, flash
from werkzeug.utils import secure_filename
import xml.etree.ElementTree as ET
import folium
from processor import (
    extract_kml_from_kmz,
    delete_files_in_folder,
    remove_cdata_from_kml,
    extract_coordinates_from_kml,
    merge_kml_files
)

app = Flask(__name__)
app.secret_key = "secret"
UPLOAD_FOLDER = "kmz"
KML_FOLDER = "kml"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(KML_FOLDER, exist_ok=True)

CITIES = [
    "Zagreb", "Split", "Dubrovnik", "Zadar",
    "Rijeka", "Varaždin", "Opatija", "Pula", "Poreč"
]

@app.route("/", methods=["GET", "POST"])
def index():
    sql_output = ""
    coordinates = []
    polygons = []
    zip_file_ready = False
    map_path = None

    if request.method == "POST":
        delete_files_in_folder(UPLOAD_FOLDER)
        delete_files_in_folder(KML_FOLDER)

        files = request.files.getlist("files")
        city = request.form.get("custom_city") or request.form.get("selected_city")

        if not city:
            flash("Please select or enter a city.")
            return redirect("/")

        if not files:
            flash("Please upload at least one KMZ or KML file.")
            return redirect("/")

        count = 30000

        for uploaded_file in files:
            filename = secure_filename(uploaded_file.filename)
            ext = os.path.splitext(filename)[1].lower()
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            uploaded_file.save(file_path)

            if ext == ".kmz":
                kml_path = extract_kml_from_kmz(file_path, KML_FOLDER)
            elif ext == ".kml":
                kml_path = os.path.join(KML_FOLDER, filename)
                shutil.move(file_path, kml_path)
            else:
                continue

            cleaned_kml = remove_cdata_from_kml(kml_path)

            uuid_match = re.search(r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', filename)
            working_street_id = uuid_match.group(0) if uuid_match else city.replace(" ", "_")

            output_buffer = io.StringIO()
            with contextlib.redirect_stdout(output_buffer):
                count = extract_coordinates_from_kml(cleaned_kml, count, working_street_id)

            sql_output += output_buffer.getvalue()

            # Extract for map
            try:
                tree = ET.parse(cleaned_kml)
                root = tree.getroot()
                ns = {'kml': 'http://www.opengis.net/kml/2.2'}
                for placemark in root.findall('.//kml:Placemark', ns):
                    for coords_element in placemark.findall('.//kml:coordinates', ns):
                        coords_text = coords_element.text.strip()
                        polygon_coords = []

                        for coord in coords_text.split():
                            parts = coord.split(',')
                            if len(parts) >= 2:
                                lon, lat = float(parts[0]), float(parts[1])
                                coordinates.append({"lat": lat, "lon": lon})
                                polygon_coords.append((lat, lon))

                        if polygon_coords:
                            polygons.append(polygon_coords)
            except Exception as e:
                flash(f"Error parsing {filename}: {str(e)}")

        if polygons:
            # Generate Folium map
            center = polygons[0][0]
            fmap = folium.Map(location=center, zoom_start=14)
            for poly in polygons:
                folium.Polygon(poly, color="blue", weight=2, fill=True, fill_opacity=0.2).add_to(fmap)

            map_path = os.path.join("static", "map.html")
            fmap.save(map_path)

        # ZIP output
        merge_kml_files(KML_FOLDER, os.path.join(KML_FOLDER, "merged_output.kml"), count)
        with zipfile.ZipFile("static/output.zip", "w") as zipf:
            for f in os.listdir(KML_FOLDER):
                if f.endswith(".kml"):
                    zipf.write(os.path.join(KML_FOLDER, f), arcname=f)
        zip_file_ready = True

    return render_template("index.html",
                           cities=CITIES,
                           sql_output=sql_output,
                           coordinates=coordinates,
                           map_path=map_path,
                           zip_file_ready=zip_file_ready)
