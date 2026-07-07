import os
import math
import webbrowser
from threading import Timer
from flask import Flask, render_template, request, redirect, session
import mysql.connector

app = Flask(__name__)
app.secret_key = "secret123"

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371.0  # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="projectuser",
        password="project123",
        database="disaster_relief"
    )

def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS help_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100),
            phone VARCHAR(20),
            help_type VARCHAR(50),
            latitude DECIMAL(10, 8),
            longitude DECIMAL(11, 8),
            status VARCHAR(20) DEFAULT 'Pending',
            assigned_volunteer VARCHAR(100)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS volunteer (
            volunteer_id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100),
            phone VARCHAR(20),
            email VARCHAR(100) UNIQUE,
            city VARCHAR(50),
            latitude DECIMAL(10, 8),
            longitude DECIMAL(11, 8),
            password VARCHAR(100) DEFAULT 'vol123'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS disaster (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reliefcamp (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100)
        )
    """)
    
    conn.commit()
    cursor.close()
    conn.close()

@app.route('/')
def index():
    # Main landing page for all users
    return render_template("index.html")

@app.route('/admin_dashboard')
def admin_dashboard():

    if 'admin' not in session:
        return redirect('/admin_login')

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM volunteer")
        volunteers = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM disaster")
        disasters = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM reliefcamp")
        camps = cursor.fetchone()[0]

        cursor.execute("SELECT volunteer_id, name, phone, city, latitude, longitude, email FROM volunteer")
        volunteer_list = cursor.fetchall()

        cursor.execute("""
            SELECT h.id, h.name, h.phone, h.help_type, h.latitude, h.longitude, h.status, 
                   COALESCE(v.name, h.assigned_volunteer) AS assigned_volunteer 
            FROM help_requests h 
            LEFT JOIN volunteer v ON h.assigned_volunteer = v.email 
            ORDER BY h.id DESC
        """)
        help_requests = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "dashboard.html",
        volunteers=volunteers,
        disasters=disasters,
        camps=camps,
        volunteer_list=volunteer_list,
        help_requests=help_requests
    )

@app.route('/admin_login', methods=['GET','POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == "admin" and password == "admin123":
            session['admin'] = True
            return redirect('/admin_dashboard')
    return render_template("login.html")

@app.route('/logout')
def logout():
    session.pop('admin', None)
    session.pop('volunteer', None)
    return redirect('/')

@app.route('/add_volunteer', methods=['POST'])
def add_volunteer():
    name = request.form['name']
    phone = request.form['phone']
    email = request.form['email']
    city = request.form['city']
    latitude = request.form.get('latitude')
    longitude = request.form.get('longitude')
    password = request.form.get('password', 'vol123')
    
    lat_val = float(latitude) if latitude and latitude.strip() else None
    lon_val = float(longitude) if longitude and longitude.strip() else None

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO volunteer (name, phone, email, city, latitude, longitude, password) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (name, phone, email, city, lat_val, lon_val, password)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    return redirect('/admin_dashboard?msg=vol_added')

@app.route('/edit_volunteer/<int:vol_id>', methods=['POST'])
def edit_volunteer(vol_id):
    if 'admin' not in session: return redirect('/admin_login')
    if not vol_id:
        return redirect('/admin_dashboard?error=invalid_id')
    phone = request.form.get('phone')
    city = request.form.get('city')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE volunteer SET phone=%s, city=%s WHERE volunteer_id=%s", (phone, city, vol_id))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect('/admin_dashboard?msg=vol_updated')

@app.route('/delete_volunteer/<int:vol_id>', methods=['POST'])
def delete_volunteer(vol_id):
    if 'admin' not in session: return redirect('/admin_login')
    if not vol_id:
        return redirect('/admin_dashboard?error=invalid_id')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM volunteer WHERE volunteer_id=%s", (vol_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect('/admin_dashboard?msg=deleted')

@app.route('/delete_request/<int:req_id>', methods=['POST'])
def delete_request(req_id):
    if 'admin' not in session: return redirect('/admin_login')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM help_requests WHERE id=%s", (req_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect('/admin_dashboard?msg=req_deleted')

@app.route('/auto_assign/<int:req_id>', methods=['POST'])
def auto_assign(req_id):
    if 'admin' not in session: return redirect('/admin_login')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT latitude, longitude FROM help_requests WHERE id=%s", (req_id,))
    req_row = cursor.fetchone()
    if not req_row or not req_row[0] or not req_row[1]:
        return redirect('/admin_dashboard?error=no_location')
        
    req_lat, req_lon = float(req_row[0]), float(req_row[1])
    
    cursor.execute("SELECT email, name, latitude, longitude FROM volunteer")
    volunteers = cursor.fetchall()
    
    nearest_vol = None
    min_dist = float('inf')
    
    for vol in volunteers:
        if vol[2] and vol[3]: # if lat & lon exist
            v_lat, v_lon = float(vol[2]), float(vol[3])
            dist = calculate_distance(req_lat, req_lon, v_lat, v_lon)
            if dist < min_dist:
                min_dist = dist
                nearest_vol = vol[1] # Set by Name
                
    if nearest_vol:
        cursor.execute("UPDATE help_requests SET status='Accepted', assigned_volunteer=%s WHERE id=%s", (f"{nearest_vol} (Auto)", req_id))
        conn.commit()
        return redirect('/admin_dashboard?msg=assigned')
    return redirect('/admin_dashboard?error=no_volunteers')

@app.route('/api/get_requests')
def api_get_requests():
    if 'admin' not in session: return {"error": "unauthorized"}
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT h.id, h.name, h.phone, h.help_type, h.latitude, h.longitude, h.status, 
               COALESCE(v.name, h.assigned_volunteer) AS assigned_volunteer 
        FROM help_requests h 
        LEFT JOIN volunteer v ON h.assigned_volunteer = v.email 
        ORDER BY h.id DESC
    """)
    cols = [col[0] for col in cursor.description]
    rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return {"requests": rows}

@app.route('/volunteer_login', methods=['GET', 'POST'])
def volunteer_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        # Select id and email for session
        cursor.execute("SELECT volunteer_id, email FROM volunteer WHERE email=%s AND password=%s", (email, password))
        vol = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if vol:
            session['volunteer'] = vol[1] # Store email in session
            return redirect('/volunteer_dashboard')
        return render_template("volunteer_login.html", error="Invalid credentials")
    return render_template("volunteer_login.html")

@app.route('/volunteer_dashboard')
def volunteer_dashboard():
    if 'volunteer' not in session:
        return redirect('/volunteer_login')
        
    vol_email = session['volunteer']
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT latitude, longitude FROM volunteer WHERE email=%s", (vol_email,))
    vol_row = cursor.fetchone()
    v_lat, v_lon = None, None
    if vol_row and vol_row[0] is not None and vol_row[1] is not None:
        v_lat, v_lon = float(vol_row[0]), float(vol_row[1])

    cursor.execute("SELECT id, name, phone, help_type, latitude, longitude, status FROM help_requests WHERE status='Pending' OR status IS NULL")
    raw_reqs = cursor.fetchall()
    
    pending_requests = []
    for r in raw_reqs:
        dist = 'Unknown'
        r_lat, r_lon = r[4], r[5]
        if v_lat and v_lon and r_lat and r_lon:
            dist = round(calculate_distance(v_lat, v_lon, float(r_lat), float(r_lon)), 1)
        pending_requests.append(r + (dist,))

    cursor.close()
    conn.close()
    
    return render_template("volunteer_dashboard.html", requests=pending_requests)

@app.route('/accept_request/<int:req_id>', methods=['POST'])
def accept_request(req_id):
    if 'volunteer' not in session: return redirect('/volunteer_login')
    vol_email = session['volunteer']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE help_requests SET status='Accepted', assigned_volunteer=%s WHERE id=%s", (vol_email, req_id))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect('/volunteer_dashboard?msg=accepted')

@app.route('/decline_request/<int:req_id>', methods=['POST'])
def decline_request(req_id):
    if 'volunteer' not in session: return redirect('/volunteer_login')
    return redirect('/volunteer_dashboard?msg=declined')

@app.route('/api/get_pending_requests')
def api_get_pending_requests():
    if 'volunteer' not in session: return {"error": "unauthorized"}
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, phone, help_type, latitude, longitude, status FROM help_requests WHERE status='Pending' OR status IS NULL")
    cols = [col[0] for col in cursor.description]
    rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return {"requests": rows}

@app.route('/request_help', methods=['GET', 'POST'])
def request_help():
    if request.method == 'POST':
        name = request.form.get('name', '')
        phone = request.form.get('phone', '')
        help_type = request.form.get('help_type', '')
        latitude = request.form.get('latitude', '')
        longitude = request.form.get('longitude', '')

        lat_val = float(latitude) if latitude.strip() else None
        lon_val = float(longitude) if longitude.strip() else None

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO help_requests (name, phone, help_type, latitude, longitude, status) VALUES (%s,%s,%s,%s,%s, 'Pending')",
                (name, phone, help_type, lat_val, lon_val)
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()
        return redirect('/request_help?success=1')
    
    return render_template("request_help.html")

if __name__ == '__main__':
    create_tables()

    try:
        conn = get_db_connection()
        if conn.is_connected():
            print("Connected to MySQL Database")
        conn.close()
    except Exception as e:
        print("Connection Failed:", e)

    def open_browser():
        url = "http://127.0.0.1:5000/"
        try:
            # Attempt to use Chrome by its default registered name
            webbrowser.get('chrome').open(url)
        except webbrowser.Error:
            # On Windows, try explicit paths if 'chrome' isn't registered
            chrome_paths = [
                "C:/Program Files/Google/Chrome/Application/chrome.exe %s",
                "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe %s"
            ]
            for path in chrome_paths:
                try:
                    webbrowser.get(path).open(url)
                    return
                except webbrowser.Error:
                    continue
            # Fallback to the system default browser if Chrome is missing
            webbrowser.open(url)

    # Automatically open the web browser after a short delay
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        Timer(1.5, open_browser).start()

    app.run(debug=True)