import sys
import os
sys.path.append(os.getcwd())

import subprocess
import re
from pathlib import Path
from io import BytesIO
from datetime import datetime
import threading
import uuid
from docx.oxml.ns import qn

import torch
import torch.nn as nn
import torch.optim as optim

from flask import (
    Flask, render_template_string, request, redirect,
    url_for, session, send_file, send_from_directory
)
from werkzeug.utils import secure_filename

from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

from IPython.display import FileLink, display
from collections import defaultdict

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from datetime import datetime
# … inne importy …
# import GeneratedPlan nie jest potrzebny, bo klasa znajduje się w tym samym pliku
from flask import session, redirect, url_for, render_template_string


# Ustawienie urządzenia: GPU, jeśli dostępne; w przeciwnym razie CPU.
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Używane urządzenie: {device}")


# Globalny słownik cen zabiegów – wartości domyślne
treatment_prices = {
    "Mikroskopowe leczenie odtwórcze": 500,
    "Weryfikacja zębów po leczeniu kanałowym": 500,
    "Odbudowa protetyczna - nakład": 1900,
    "Konsultacja implantologiczna celem odbudowy braku zęba": 250,
    "Gingiwoplastyka": 0
}
# ---------------------------
# Opisy zabiegów – wartości domyślne
# ---------------------------
treatment_descriptions = {
    "Mikroskopowe leczenie odtwórcze": "Standardowy opis leczenia odtwórczego pod mikroskopem…",
    "Weryfikacja zębów po leczeniu kanałowym": "Standardowy opis weryfikacji po leczeniu kanałowym…",
    "Odbudowa protetyczna - nakład": "Standardowy opis odbudowy protetycznej nakładem…",
    "Konsultacja implantologiczna celem odbudowy braku zęba": "Standardowy opis konsultacji implantologicznej…",
    "Gingiwoplastyka": "Standardowy opis gingiwoplastyka…"
}


# ---------------------------
# In‐memory storage gabinetów i zabiegów
# ---------------------------
# każdy gabinet: {'id': str, 'name': str, 'logo': filename_or_None}
# cabinets = []
# każdy zabieg: {'id': str, 'cabinet_id': str, 'type': str, 'description': str, 'price': float}
# treatments = []
# lista nieedytowalnych typów zabiegów
# TREATMENT_TYPES = list(treatment_prices.keys())


app.secret_key = os.environ.get("SECRET_KEY","change-me")


# ——— Wbudowany CSS w jednej zmiennej ———
CSS = """
body {
    font-family: Arial, sans-serif;
    background-color: #f5f5f5;
    margin: 0;
    padding: 0;
}
.container {
    max-width: 800px;
    margin: auto;
    padding: 20px;
}

"""

# ——— Endpoint serwujący CSS pod ścieżką /static/style.css ———
#from flask import Response
#@app.route("/static/style.css")
#def style_css():
    #return Response(CSS, mimetype="text/css")


from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app.config['SQLALCHEMY_DATABASE_URI']   = 'sqlite:///lotti.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ---------------------------
# MODELE BAZY DANYCH (ORM)
# ---------------------------
# … po `db = SQLAlchemy(app)` …

class User(db.Model):
    __tablename__ = 'user'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    cabinets      = db.relationship('Cabinet', backref='owner', lazy=True)

    def set_password(self, pwd):
        self.password_hash = generate_password_hash(pwd)

    def check_password(self, pwd):
        return check_password_hash(self.password_hash, pwd)


class TreatmentType(db.Model):
    __tablename__ = 'treatment_type'
    id                  = db.Column(db.Integer, primary_key=True)
    name                = db.Column(db.String(64), unique=True, nullable=False)
    default_price       = db.Column(db.Float, nullable=False)
    default_description = db.Column(db.Text,   nullable=True)

class ProcedureCode(db.Model):
    __tablename__ = 'procedure_code'
    code             = db.Column(db.String(16), primary_key=True)
    category_name    = db.Column(db.String(64), db.ForeignKey('treatment_type.name'), nullable=False)
    default_duration = db.Column(db.Integer, nullable=False)



class Treatment(db.Model):
    __tablename__ = 'treatment'
    id         = db.Column(db.Integer, primary_key=True)
    cabinet_id = db.Column(db.Integer, db.ForeignKey('cabinet.id'), nullable=False)
    type       = db.Column(db.String(64), nullable=False)
    description= db.Column(db.Text)
    price      = db.Column(db.Float)
        # realny czas wpisany przez lekarza (minuty)
    duration = db.Column(db.Integer, nullable=True)
    base_price      = db.Column(db.Float, nullable=True)   # cena podstawowa
    per_tooth_price = db.Column(db.Float, nullable=True)   # cena za ząb




class Cabinet(db.Model):
    __tablename__ = 'cabinet'
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(128), nullable=False)
    logo         = db.Column(db.String(256))
    doctor_name  = db.Column(db.String(128))
    street       = db.Column(db.String(128))
    flat_number  = db.Column(db.String(16))
    postal_code  = db.Column(db.String(16))
    city         = db.Column(db.String(64))
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    treatments   = db.relationship('Treatment', backref='cabinet', lazy=True)

class CodeDuration(db.Model):
    __tablename__ = 'code_duration'
    id              = db.Column(db.Integer, primary_key=True)
    cabinet_id      = db.Column(db.Integer, db.ForeignKey('cabinet.id'), nullable=False)
    procedure_code  = db.Column(db.String(16), db.ForeignKey('procedure_code.code'), nullable=False)
    duration        = db.Column(db.Integer, nullable=False)
    timestamp       = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    cabinet = db.relationship('Cabinet', backref='code_durations')
    code    = db.relationship('ProcedureCode')

class GeneratedPlan(db.Model):
    __tablename__ = "generated_plan"
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    cabinet_id   = db.Column(db.Integer, db.ForeignKey('cabinet.id'), nullable=False)
    input_data   = db.Column(db.Text,   nullable=False)
    plan_text    = db.Column(db.Text,   nullable=False)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relacje (opcjonalnie, ale ułatwiają późniejsze zapytania)
    user          = db.relationship('User', backref='generated_plans')
    cabinet       = db.relationship('Cabinet', backref='generated_plans')


# Folder na loga gabinetów (wewnątrz folderu static)
UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ---------------------------
# FUNKCJA ANALIZUJĄCA PODOBIEŃSTWO (ML/TOKENIZACJA)
# ---------------------------
def analyze_treatment_similarity(input_text):
    """
    Oblicza kosinusową miarę podobieństwa między wprowadzonym tekstem a standardowymi kategoriami.
    Używamy TF-IDF do tokenizacji tekstu.
    Zwraca słownik, gdzie kluczem jest kategoria (z treatment_prices), a wartością miara podobieństwa (0-1).
    """
    standard_categories = list(treatment_prices.keys())
    vectorizer = TfidfVectorizer()
    # Dopasowujemy wektory standardowych kategorii
    standard_vectors = vectorizer.fit_transform(standard_categories)
    # Transformujemy wprowadzony tekst
    input_vector = vectorizer.transform([input_text])
    # Obliczamy kosinusową miarę podobieństwa
    similarities = cosine_similarity(input_vector, standard_vectors)
    return dict(zip(standard_categories, similarities[0]))

# ---------------------------
# PANEL LOGOWANIA – szablon logowania
# ---------------------------
login_template = """
<!doctype html>
<html lang="pl">
<head>
    <meta charset="utf-8">
    <title>Panel Logowania</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; text-align: center; }
        form { display: inline-block; margin-top: 20px; }
    </style>
</head>
<body>
    <img src="{{ url_for('static', filename='Lottiimage.png') }}" alt="Logo" style="max-width:200px; margin-bottom: 100px;">
    <h1>Logowanie do systemu</h1>
    {% if error %}
      <p style="color: red;">{{ error }}</p>
    {% endif %}
    <form method="POST" action="/login">
        <label for="username">Nazwa użytkownika:</label><br>
        <input type="text" id="username" name="username"><br><br>
        <label for="password">Hasło:</label><br>
        <input type="password" id="password" name="password"><br><br>
        <button type="submit">Zaloguj</button>
    </form>
</body>
</html>
"""

# ------------------------
# Szablon: lista gabinetów
# ------------------------
cabinets_template = """
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <title>AdminLotti – Gabinety</title>

  <!-- Bootstrap CSS -->
  <link
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
    rel="stylesheet">

  <!-- FontAwesome -->
  <link
    href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.1.1/css/all.min.css"
    rel="stylesheet">

  <style>
    body {
      background: #f0f4f8;
      color: #33475b;
      padding-top: 1rem;
      padding-bottom: 2rem;
    }
    .navbar {
      background: #ffffffcc;
      box-shadow: 0 2px 8px rgba(0,0,0,0.05);
      backdrop-filter: blur(10px);
    }
    .navbar-brand, .nav-link {
      color: #33475b !important;
      font-weight: 500;
    }
    .btn-rounded {
      border-radius: 50px;
      padding: .5rem 1.25rem;
      transition: all .2s ease-in-out;
    }
    .btn-rounded:hover {
      transform: translateY(-2px);
    }
    .card-custom {
      border: none;
      border-radius: .75rem;
      box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }
  </style>
</head>

<body>
  <!-- Navbar -->
  <nav class="navbar navbar-expand-lg sticky-top mb-4">
    <div class="container">
      <a class="navbar-brand" href="/"><i class="fa-solid fa-tooth me-2"></i>ChatLotti</a>
      <div class="ms-auto">
        <a class="nav-link d-inline px-3" href="/"><i class="fa-solid fa-calendar-check me-1"></i>Generuj plan</a>
        <a class="nav-link d-inline px-3" href="/logout"><i class="fa-solid fa-right-from-bracket me-1"></i>Wyloguj</a>
      </div>
    </div>
  </nav>

  <div class="container">
    <!-- Lista gabinetów -->
    <div class="card card-custom mb-4">
      <div class="card-body">
        <h5 class="card-title"><i class="fa-solid fa-building me-2"></i>Zarządzanie gabinetami</h5>
        {% if message %}
          <div class="alert alert-success">{{ message }}</div>
        {% endif %}

        <table class="table align-middle">
          <thead class="table-light">
            <tr>
              <th>Nazwa</th>
              <th>Logo</th>
              <th>Akcje</th>
            </tr>
          </thead>
          <tbody>
            {% for c in cabinets %}
              <tr>
                <td>{{ c.name }}</td>
                <td>
                  {% if c.logo %}
                    <img src="{{ url_for('static', filename='uploads/' ~ c.logo) }}"
                         class="img-fluid rounded" style="max-height:40px;">
                  {% endif %}
                </td>
                <td>
                  <a class="btn btn-sm btn-outline-primary btn-rounded"
                     href="{{ url_for('admin_treatments', cabinet_id=c.id) }}">
                    <i class="fa-solid fa-tooth me-1"></i>Zabiegi
                  </a>
                </td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Formularz dodawania gabinetu -->
    <div class="card card-custom">
      <div class="card-body">
        <h5 class="card-title"><i class="fa-solid fa-plus me-2"></i>Dodaj nowy gabinet</h5>
        <form method="post" enctype="multipart/form-data">
          <div class="row g-3">
            <div class="col-md-6">
              <label class="form-label">Nazwa gabinetu</label>
              <input type="text" name="name" class="form-control" required>
            </div>
            <div class="col-md-6">
              <label class="form-label">Logo gabinetu</label>
              <input type="file" name="logo" class="form-control" accept="image/*">
            </div>
            <div class="col-md-6">
              <label class="form-label">Imię i nazwisko lekarza</label>
              <input type="text" name="doctor_name" class="form-control" required>
            </div>
            <div class="col-md-6">
              <label class="form-label">Ulica</label>
              <input type="text" name="street" class="form-control" required>
            </div>
            <div class="col-md-3">
              <label class="form-label">Numer lokalu</label>
              <input type="text" name="flat_number" class="form-control">
            </div>
            <div class="col-md-3">
              <label class="form-label">Kod pocztowy</label>
              <input type="text" name="postal_code" pattern="\\d{2}-\\d{3}"
                     class="form-control" placeholder="00-000" required>
            </div>
            <div class="col-md-6">
              <label class="form-label">Miejscowość</label>
              <input type="text" name="city" class="form-control" required>
            </div>
          </div>
          <div class="mt-4">
            <button type="submit" class="btn btn-primary btn-rounded">
              <i class="fa-solid fa-plus me-1"></i>Dodaj gabinet
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>

  <!-- Bootstrap JS Bundle -->
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""



# ---------------------------------------
# Szablon: lista + formularz zabiegów gabinetu
# ---------------------------------------
treatments_template = """
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <title>Zabiegi gabinetu</title>

  <!-- Bootstrap CSS -->
  <link
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
    rel="stylesheet">

  <!-- FontAwesome -->
  <link
    href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.1.1/css/all.min.css"
    rel="stylesheet">

  <style>
    body {
      background: #f0f4f8;
      color: #33475b;
      padding-top: 1rem;
      padding-bottom: 2rem;
    }
    .navbar {
      background: #ffffffcc;
      box-shadow: 0 2px 8px rgba(0,0,0,0.05);
      backdrop-filter: blur(10px);
    }
    .navbar-brand, .nav-link {
      color: #33475b !important;
      font-weight: 500;
    }
    .btn-rounded {
      border-radius: 50px;
      padding: .5rem 1.25rem;
      transition: all .2s ease-in-out;
    }
    .btn-rounded:hover {
      transform: translateY(-2px);
    }
    .card-custom {
      border: none;
      border-radius: .75rem;
      box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }
  </style>
</head>

<body>
<!-- Navbar -->
<nav class="navbar navbar-expand-lg sticky-top mb-4">
  <div class="container">
    <a class="navbar-brand" href="/"><i class="fa-solid fa-tooth me-2"></i>ChatLotti</a>
    <div class="ms-auto">
      <a class="nav-link d-inline px-3" href="/plans"><i class="fa-solid fa-file-alt me-1"></i>Wygenerowane plany</a>
      <a class="nav-link d-inline px-3" href="/"><i class="fa-solid fa-calendar-check me-1"></i>Generuj plan</a>
      <a class="nav-link d-inline px-3" href="/admin/cabinets"><i class="fa-solid fa-hospital me-1"></i>Gabinety</a>
      <a class="nav-link d-inline px-3" href="/logout"><i class="fa-solid fa-right-from-bracket me-1"></i>Wyloguj</a>
    </div>
  </div>
</nav>


  <div class="container">
    <!-- Lista zabiegów -->
    <div class="card card-custom mb-4">
      <div class="card-body">
        <h5 class="card-title"><i class="fa-solid fa-list me-2"></i>Zabiegi w gabinecie &ldquo;{{ cabinet.name }}&rdquo;</h5>
        {% if message %}
          <div class="alert alert-success">{{ message }}</div>
        {% endif %}

        <table class="table align-middle">
          <thead class="table-light">
            <tr>
              <th>Rodzaj</th>
              <th>Opis</th>
              <th>Cena</th>
              <th>Akcje</th>
              <th>Usuń</th>
            </tr>
          </thead>
          <tbody>
            {% for t in treatments %}
              <tr>
                <td>{{ t.type }}</td>
                <td>{{ t.description }}</td>
                <td>
                  {% if t.type == "Gingiwoplastyka" %}
                    {{ t.base_price }} zł + {{ t.per_tooth_price }} zł/ząb
                  {% else %}
                    {{ t.price }} zł
                  {% endif %}
                </td>
                <td>
                  <a class="btn btn-sm btn-outline-primary btn-rounded me-2"
                     href="{{ url_for('edit_treatment', cabinet_id=cabinet.id, treatment_id=t.id) }}">
                    <i class="fa-solid fa-pen-to-square me-1"></i>Edytuj
                  </a>
                  <a class="btn btn-sm btn-outline-secondary btn-rounded"
                     href="{{ url_for('add_duration', cabinet_id=cabinet.id, treatment_id=t.id) }}">
                    <i class="fa-solid fa-clock me-1"></i>Dodaj czas
                  </a>
                </td>
                <td>
                  <form method="POST"
                        action="{{ url_for('delete_treatment', cabinet_id=cabinet.id, treatment_id=t.id) }}"
                        onsubmit="return confirm('Czy na pewno chcesz usunąć ten zabieg?');">
                    <button type="submit" class="btn btn-sm btn-outline-danger btn-rounded">
                      <i class="fa-solid fa-trash me-1"></i>Usuń
                    </button>
                  </form>
                </td>
              </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Formularz dodawania zabiegu -->
    <div class="card card-custom">
      <div class="card-body">
        <h5 class="card-title"><i class="fa-solid fa-plus me-2"></i>Dodaj zabieg</h5>
        <form method="post">
          <div class="mb-3">
            <label class="form-label">Rodzaj</label>
            <select name="type" class="form-select" required>
              {% for tt in types %}
                <option value="{{ tt.name }}">{{ tt.name }}</option>
              {% endfor %}
            </select>
          </div>
          <div class="mb-3">
            <label class="form-label">Opis</label>
            <textarea name="description" class="form-control" rows="2"></textarea>
          </div>
            <!-- wspólne pola -->
          <div class="mb-3" id="price-field">
            <label class="form-label">Cena (PLN)</label>
            <input type="number" name="price" class="form-control" required>
          </div>

          <!-- dodatkowe pola tylko dla Gingiwoplastyka -->
          <div id="gingi-prices" style="display:none;">
            <div class="mb-3">
              <label class="form-label">Cena podstawowa (PLN)</label>
              <input type="number" step="0.01" name="base_price" class="form-control">
            </div>
            <div class="mb-3">
              <label class="form-label">Cena za 1 ząb (PLN)</label>
              <input id="per-tooth-price" type="number" step="0.01" name="per_tooth_price" class="form-control">
            </div>
          </div>

          <script>
            const typeSelect    = document.querySelector('select[name="type"]');
            const priceField    = document.getElementById('price-field');
            const gingiPrices   = document.getElementById('gingi-prices');
            const priceInput    = document.querySelector('input[name="price"]');
            const baseInput     = document.querySelector('input[name="base_price"]');
            const perToothInput = document.getElementById('per-tooth-price');

            function toggleFields() {
              const isGingi = typeSelect.value === 'Gingiwoplastyka';
              priceField.style.display    = isGingi ? 'none' : 'block';
              gingiPrices.style.display   = isGingi ? 'block' : 'none';
              priceInput.required         = !isGingi;
              baseInput.required          = isGingi;
              perToothInput.required      = isGingi;
            }

            typeSelect.addEventListener('change', toggleFields);
            // przy pierwszym ładowaniu formularza
            toggleFields();
          </script>

          <button type="submit" class="btn btn-primary btn-rounded">
            <i class="fa-solid fa-plus me-1"></i>Dodaj zabieg
          </button>
        </form>
      </div>
    </div>
  </div>

  <!-- Bootstrap JS Bundle -->
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""



# ---------------------------------------
# Szablon: edycja pojedynczego zabiegu
# ---------------------------------------
edit_treatment_template = """
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <title>Edytuj zabieg</title>

  <!-- Bootstrap CSS -->
  <link
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
    rel="stylesheet">

  <!-- FontAwesome -->
  <link
    href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.1.1/css/all.min.css"
    rel="stylesheet">

  <style>
    body {
      background: #f0f4f8;
      color: #33475b;
      padding-top: 1rem;
      padding-bottom: 2rem;
    }
    .navbar {
      background: #ffffffcc;
      box-shadow: 0 2px 8px rgba(0,0,0,0.05);
      backdrop-filter: blur(10px);
    }
    .navbar-brand, .nav-link {
      color: #33475b !important;
      font-weight: 500;
    }
    .btn-rounded {
      border-radius: 50px;
      padding: .5rem 1.25rem;
      transition: all .2s ease-in-out;
    }
    .btn-rounded:hover {
      transform: translateY(-2px);
    }
    .card-custom {
      border: none;
      border-radius: .75rem;
      box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }
    .form-label {
      font-weight: 500;
    }
  </style>
</head>

<body>
 <!-- Navbar -->
<nav class="navbar navbar-expand-lg sticky-top mb-4">
  <div class="container">
    <a class="navbar-brand" href="/"><i class="fa-solid fa-tooth me-2"></i>ChatLotti</a>
    <div class="ms-auto">
      <a class="nav-link d-inline px-3" href="/plans"><i class="fa-solid fa-file-alt me-1"></i>Wygenerowane plany</a>
      <a class="nav-link d-inline px-3" href="/"><i class="fa-solid fa-calendar-check me-1"></i>Generuj plan</a>
      <a class="nav-link d-inline px-3" href="/admin/cabinets"><i class="fa-solid fa-hospital me-1"></i>Gabinety</a>
      <a class="nav-link d-inline px-3" href="/logout"><i class="fa-solid fa-right-from-bracket me-1"></i>Wyloguj</a>
    </div>
  </div>
</nav>


  <div class="container">
    <div class="card card-custom mx-auto" style="max-width: 600px;">
      <div class="card-body">
        <h5 class="card-title mb-4"><i class="fa-solid fa-pen-to-square me-2"></i>Edytuj zabieg „{{ treatment.type }}”</h5>
        <form method="post">
          <div class="mb-3">
            <label class="form-label">Rodzaj (nieedytowalny):</label>
            <input type="text"
                   class="form-control"
                   value="{{ treatment.type }}"
                   disabled>
          </div>
          <div class="mb-3">
            <label class="form-label">Opis:</label>
            <textarea name="description"
                      class="form-control"
                      rows="2">{{ treatment.description }}</textarea>
          </div>
          <div class="mb-3">
            <label class="form-label">Cena (PLN):</label>
            <input type="number"
                   name="price"
                   class="form-control"
                   value="{{ treatment.price }}"
                   required>
          </div>
          <div class="d-flex justify-content-between">
            <a href="{{ url_for('admin_treatments', cabinet_id=cabinet.id) }}"
               class="btn btn-outline-secondary btn-rounded">
              <i class="fa-solid fa-arrow-left me-1"></i>Powrót
            </a>
            <button type="submit"
                    class="btn btn-primary btn-rounded">
              <i class="fa-solid fa-check me-1"></i>Zapisz zmiany
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>

  <!-- Bootstrap JS Bundle -->
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session["user_id"] = user.id
            return redirect(url_for("index"))
        else:
            error = "Niepoprawna nazwa użytkownika lub hasło."
    return render_template_string(login_template, error=error)


durations_template = """
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <title>Dodaj czas wizyty</title>

  <!-- Bootstrap CSS -->
  <link
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
    rel="stylesheet">

  <!-- FontAwesome -->
  <link
    href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.1.1/css/all.min.css"
    rel="stylesheet">

  <style>
    body {
      background: #f0f4f8;
      color: #33475b;
      padding-top: 1rem;
      padding-bottom: 2rem;
    }
    .navbar {
      background: #ffffffcc;
      box-shadow: 0 2px 8px rgba(0,0,0,0.05);
      backdrop-filter: blur(10px);
    }
    .navbar-brand, .nav-link {
      color: #33475b !important;
      font-weight: 500;
    }
    .card-custom {
      border: none;
      border-radius: .75rem;
      box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }
    .btn-rounded {
      border-radius: 50px;
      padding: .5rem 1.25rem;
      transition: all .2s ease-in-out;
    }
    .btn-rounded:hover {
      transform: translateY(-2px);
    }

    /* Kontener na tabelę historii – ograniczona wysokość, przewijalność */
    .history-container {
      max-height: 250px;
      overflow-y: auto;
      margin-bottom: 1rem;
    }
    .history-container table {
      margin-bottom: 0;
    }
  </style>
</head>

<body>
  <!-- Navbar -->
  <nav class="navbar navbar-expand-lg sticky-top mb-4">
    <div class="container">
      <a class="navbar-brand" href="/"><i class="fa-solid fa-tooth me-2"></i>ChatLotti</a>
      <div class="ms-auto">
        <a class="nav-link d-inline px-3" href="/admin/cabinets">
          <i class="fa-solid fa-hospital me-1"></i>Gabinety
        </a>
        <a class="nav-link d-inline px-3" href="/logout">
          <i class="fa-solid fa-right-from-bracket me-1"></i>Wyloguj
        </a>
      </div>
    </div>
  </nav>

  <div class="container">
    <div class="card card-custom p-4">
      <h5 class="card-title mb-3">
        <i class="fa-solid fa-clock me-2"></i>Dodaj czas wizyty dla „{{ treatment.type }}”
      </h5>

      <!-- CZĘŚĆ 1: Tabela historii (zawsze się pokazuje) -->
      <div class="history-container">
        <table class="table table-striped table-bordered">
          <thead class="table-light">
            <tr>
              <th scope="col">Rodzaj zabiegu</th>
              <th scope="col">Kod procedury</th>
              <th scope="col">Wszystkie dodane czasy [min]</th>
              <th scope="col">Optymalny czas [min]</th>  <!-- TUTAJ dodaliśmy nową kolumnę -->
            </tr>
          </thead>
          <tbody>
            {% if history_groups %}
              {% for group in history_groups %}
                <tr>
                  <td>{{ group.category }}</td>
                  <td>{{ group.procedure_code }}</td>
                  <td>{{ group.durations | join(', ') }} min</td>
                  <td>{{ group.optimal }} min</td>  <!-- TUTAJ wyświetlamy obliczony optimal -->
                </tr>
              {% endfor %}
            {% else %}
              <tr>
                <td colspan="4" class="text-center text-muted">
                  Brak dotychczas zapisanych czasów dla tego rodzaju zabiegu.
                </td>
              </tr>
            {% endif %}
          </tbody>
        </table>
      </div>
      <!-- KONIEC: Tabela historii -->

      <p>Optymalny czas wizyty (dla bieżącego kodu): <strong>{{ optimal }} min</strong></p>

      <form method="post">
        <div class="mb-3">
          <label class="form-label">Rodzaj zabiegu</label>
          <select class="form-select" disabled>
            <option>{{ treatment.type }}</option>
          </select>
        </div>

        <div class="mb-3">
          <label class="form-label" for="code">Kod zabiegu</label>
          <input
            type="text"
            id="code"
            name="procedure_code"
            list="code-list"
            class="form-control"
            required
            value="{{ code or '' }}"
            placeholder="np. 13 MOD">
          <datalist id="code-list">
            {% for c in codes %}
              <option value="{{ c }}">
            {% endfor %}
          </datalist>
        </div>

        <div id="times" class="mb-3">
          <label class="form-label">Czas wizyty 1 (min)</label>
          <input
            type="number"
            name="new_durations[]"
            class="form-control"
            required
            placeholder="np. 75">
        </div>

        <div class="d-flex gap-2">
          <button
            type="button"
            class="btn btn-outline-secondary btn-rounded"
            onclick="addField()">
            <i class="fa-solid fa-plus me-1"></i>Dodaj kolejny czas
          </button>
          <button
            type="submit"
            class="btn btn-primary btn-rounded">
            Zapisz
          </button>
          <a
            href="{{ url_for('admin_treatments', cabinet_id=cabinet.id) }}"
            class="btn btn-outline-danger btn-rounded">
            Wyjdź
          </a>
        </div>
      </form>
    </div>
  </div>

  <!-- Bootstrap JS Bundle -->
  <script
    src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js">
  </script>
  <script>
    function addField() {
      const container = document.getElementById('times');
      const idx = container.querySelectorAll('input').length + 1;
      const div = document.createElement('div');
      div.className = 'mb-3';
      div.innerHTML = `
        <label class="form-label">Czas wizyty ${idx} (min)</label>
        <input type="number" class="form-control" name="new_durations" required placeholder="np. 80">
      `;
      container.appendChild(div);
    }
  </script>
</body>
</html>
"""




from flask import session, redirect
@app.before_request
def require_login():
    allowed_routes = ["login", "static"]
    if request.endpoint not in allowed_routes and "user_id" not in session:
        return redirect(url_for("login"))

# ---------------------------
# LOGIKA MODELU
# ---------------------------
import re

def parse_gingi_range(txt):
    """
    Z napisu typu "gingi 17 - 27" wyciąga przedział liczb od 17 do 27,
    a następnie filtruje tylko te kody, które odpowiadają prawidłowym dwucyfrowym numerom zębów:
      - Pierwsza cyfra: 1, 2, 3 lub 4
      - Druga cyfra: od 1 do 8
    W efekcie:
      parse_gingi_range("gingi 17 - 27") zwróci ["17", "18", "21", "22", "23", "24", "25", "26", "27"].
    """
    m = re.search(r'(\d{2})\s*-\s*(\d{2})', txt)
    if not m:
        return []

    a, b = int(m.group(1)), int(m.group(2))
    # 1) Wygeneruj wszystkie dwucyfrowe kody od a do b (np. 17,18,19,20,...,27)
    raw_codes = [f"{i:02d}" for i in range(a, b + 1)]

    # 2) Przefiltruj tylko te, które pasują do wzoru: [1-4][1-8]
    valid_codes = [code for code in raw_codes if re.match(r'^[1-4][1-8]$', code)]
    return valid_codes



def parse_input(input_str):
    """
    1) Dzielimy input po przecinkach: "gingi 14, 16 - 18, 27, 13 MOD" →
       tokens = ["gingi 14", "16 - 18", "27", "13 MOD"]
    2) Iterujemy po tokenach; gdy token zaczyna się od "gingi", zbieramy też kolejne
       tokeny, które są albo samymi dwucyfrowymi numerami, albo zakresem "NN - NN".
    3) Dla każdego zebranego tokenu (np. "14", "16 - 18", "27") tworzymy wpisy:
       - jeśli prosty numer -> jeden wpis
       - jeśli zakres -> dla wszystkich kodów z parse_gingi_range("gingi " + "<zakres>")
    4) Pozostałe tokeny (te, co nie zaczynały się od "gingi") interpretujemy
       jak dotychczas: dopasowanie r"(\d{2})\s*(.+)".
    """
    tokens = re.split(r",\s*", input_str.strip())
    parsed_entries = []
    i = 0
    while i < len(tokens):
        entry = tokens[i].strip()
        if not entry:
            i += 1
            continue

        # Jeżeli wpis zaczyna się od "gingi" → bierzemy też następujące tokeny typu "NN" lub "NN - NN"
        if entry.lower().startswith("gingi"):
            # 1) Usuń sam prefiks "gingi", zostaw resztę (może być od razu numer lub nic)
            rest = entry[len("gingi"):].strip()
            # 2) Zbiór tokenów do przetworzenia (pojedyncze numery lub zakresy)
            gingi_tokens = []
            if rest:
                gingi_tokens.append(rest)
            # 3) Sprawdź kolejne tokeny: dopóki one są w formacie "NN" albo "NN - NN", bierzemy je
            j = i + 1
            while j < len(tokens):
                candidate = tokens[j].strip()
                # dopuszczamy albo prosty kod "NN", albo zakres "NN - NN"
                if re.match(r"^\d{2}\s*-\s*\d{2}$", candidate) or re.match(r"^\d{2}$", candidate):
                    gingi_tokens.append(candidate)
                    j += 1
                else:
                    break
            # 4) Dla każdego takiego tokenu:
            for tok in gingi_tokens:
                tok = tok.strip()
                if "-" in tok:
                    # zakres: np. "16 - 18" → użyj parse_gingi_range("gingi 16 - 18")
                    expanded = parse_gingi_range(f"gingi {tok}")
                    for code in expanded:
                        parsed_entries.append({
                            "tooth_code":     code,
                            "treatment_code": "Gingiwoplastyka",
                            "procedure_code": f"{code} Gingiwoplastyka"
                        })
                else:
                    # sam numer: np. "14" lub "27"
                    tooth_code = tok.zfill(2)
                    parsed_entries.append({
                        "tooth_code":     tooth_code,
                        "treatment_code": "Gingiwoplastyka",
                        "procedure_code": f"{tooth_code} Gingiwoplastyka"
                    })
            # przeskocz wszystkie tokeny związane z tą "gingi"-sekcją
            i = j
            continue

        # Jeżeli nie było "gingi" na początku, traktujemy normalny wpis "NN <kod>"
        match = re.match(r"(\d{2})\s*(.+)", entry)
        if match:
            tooth_code     = match.group(1)
            treatment_code = match.group(2).strip()
            parsed_entries.append({
                "tooth_code":     tooth_code,
                "treatment_code": treatment_code,
                "procedure_code": f"{tooth_code} {treatment_code}"
            })
        # Przejdźmy do następnego tokenu
        i += 1

    return parsed_entries





def classify_entry(entry):
    tooth_code = entry['tooth_code']
    treatment = entry['treatment_code'].lower()

    # 1) Endo-weryfikacja
    if "po endo" in treatment:
        return ("Weryfikacja zębów po leczeniu kanałowym", tooth_code)

    # 2) Ekstrakcja
    if "ex" in treatment:
        return ("Do usunięcia", tooth_code)

    # 3) Brak → implant
    if treatment == "brak":
        return ("Konsultacja implantologiczna celem odbudowy braku zęba", tooth_code)

    # 4) Gingiwoplastyka (zakres)
    if "gingi" in treatment:
        return ("Gingiwoplastyka", tooth_code)

    # 5) Odbudowa protetyczna – nakład (rozpoznajemy "nakład" lub "naklad")
    if "nakład" in treatment or "naklad" in treatment:
        return ("Odbudowa protetyczna - nakład", tooth_code)

    # 6) Odbudowa protetyczna – korona (rozpoznajemy "korona")
    if "korona" in treatment:
        return ("Odbudowa protetyczna - korona", tooth_code)

    # 7) Mikroskopowe leczenie odtwórcze / Odbudowa protetyczna - nakład
    code_letters = treatment.replace(" ", "")
    if code_letters.isalpha():
        if len(code_letters) in [1, 2]:
            return ("Mikroskopowe leczenie odtwórcze", tooth_code)
        elif len(code_letters) == 3:
            # trzy litery to domyślnie "nakład"
            return ("Odbudowa protetyczna - nakład", tooth_code)

    # 8) Pozostałe – nieznana kategoria
    return (None, tooth_code)






def generate_visit_plan(parsed_entries, duration_map, price_map, per_tooth_map):
    """
    Buduje harmonogram wizyt (lista słowników) na podstawie sparsowanych wpisów.
    ...
    """

    visits = []
    idx = 1

    # ——— 1. Dodajemy zawsze na początku “Higienizację” (1 h = 60 min, koszt 0) ———
    visits.append({
        "idx":        idx,
        "label":      f"Wizyta {idx}",
        "category":   "Higienizacja",
        "unit_price": 0,
        "count":      0,
        "teeth":      [],
        "minutes":    60,
        "base_cost":  0,
        "extra":      0
    })
    idx += 1
    # ————————————————————————————————————————————————————————————————————————

    # 2. CBCT – łączymy wszystkie wpisy kategorii “Weryfikacja zębów po leczeniu kanałowym”
    #    i “Konsultacja implantologiczna celem odbudowy braku zęba” w jedną wizytę:
    cbct_cats = {
        "Weryfikacja zębów po leczeniu kanałowym",
        "Konsultacja implantologiczna celem odbudowy braku zęba"
    }
    cbct_items = [e for e in parsed_entries if classify_entry(e)[0] in cbct_cats]
    if cbct_items:
        teeth_list = [e['tooth_code'] for e in cbct_items]
        total_time = sum(duration_map.get(e['procedure_code'], 60) for e in cbct_items)
        category_cbct = classify_entry(cbct_items[0])[0]
        unit_price_cbct = price_map.get(category_cbct, 0)
        base_cost_cbct = sum(price_map.get(classify_entry(e)[0], 0) for e in cbct_items)
        visits.append({
            "idx":        idx,
            "label":      f"Wizyta {idx}",
            "category":   category_cbct,
            "unit_price": unit_price_cbct,
            "count":      len(teeth_list),
            "teeth":      teeth_list,
            "minutes":    total_time,
            "base_cost":  base_cost_cbct,
            "extra":      400  # dodatkowa opłata za CBCT
        })
        idx += 1

    # ——— 3. Pomocna funkcja do grupowania wg rzeczywistego sąsiedztwa (±2 położenia) ———
    def cluster_by_tooth_neighborhood(entries_same_category):
        """
        entries_same_category: lista wpisów {'tooth_code': 'NN', ...}
        Zwraca listę klastrów, w których uwzględniamy realne sąsiedztwo:
          - w szczęce górnej: kolejność [18,17,...,11,21,22,...,28]
          - w szczęce dolnej: kolejność [38,37,...,31,41,42,...,48]
        Łączymy te zęby, które w tej kolejności dzieli maksymalnie 2 indeksy.
        """
        # Definiujemy kolejności w szczękach:
        upper_order = [
            f"1{i}" for i in range(8, 0, -1)
        ] + [
            f"2{i}" for i in range(1, 9)
        ]
        # upper_order == ["18","17","16","15","14","13","12","11","21","22","23","24","25","26","27","28"]

        lower_order = [
            f"3{i}" for i in range(8, 0, -1)
        ] + [
            f"4{i}" for i in range(1, 9)
        ]
        # lower_order == ["38","37","36","35","34","33","32","31","41","42","43","44","45","46","47","48"]

        # Zmapujmy każdy kod na (lista, indeks)
        order_map = {}
        for idx_u, code_u in enumerate(upper_order):
            order_map[code_u] = ("upper", idx_u)
        for idx_l, code_l in enumerate(lower_order):
            order_map[code_l] = ("lower", idx_l)

        # Przyporządkujemy każdemu wpisowi (jaw, index)
        indexed = []
        for e in entries_same_category:
            cod = e["tooth_code"]
            info = order_map.get(cod)
            if info:
                jaw, pos = info
                indexed.append((jaw, pos, e))
            # jeśli kodu nie ma w mapie (teoretycznie nie powinno się zdarzyć),
            # to go pomijamy

        # Grupujemy oddzielnie górę i dół
        clusters = []
        for jaw_label in ("upper", "lower"):
            # wyciągnij tylko te odpowiadające danej szczęce
            jaw_list = [(pos, entry) for (jaw, pos, entry) in indexed if jaw == jaw_label]
            if not jaw_list:
                continue
            # posortuj po indeksie
            jaw_list.sort(key=lambda x: x[0])
            n = len(jaw_list)

            visited = [False] * n
            for i in range(n):
                if visited[i]:
                    continue
                # robimy DFS po grafie, w którym krawędzie łączą sąsiadów różniących się indeksem max o 2
                stack = [i]
                visited[i] = True
                comp_indices = []
                while stack:
                    u = stack.pop()
                    comp_indices.append(u)
                    for v in range(n):
                        if not visited[v] and abs(jaw_list[u][0] - jaw_list[v][0]) <= 2:
                            visited[v] = True
                            stack.append(v)
                # z comp_indices zbuduj cluster
                group_entries = [jaw_list[k][1] for k in comp_indices]
                clusters.append(group_entries)
        return clusters
    # ————————————————————————————————————————————————————————————————————————

    # 4. Dla pozostałych kategorii (poza CBCT i Higienizacją) – grupujemy wg nazwy zabiegu:
    cbct_and_none = cbct_cats.union({None})
    by_cat = {}
    for e in parsed_entries:
        cat, _ = classify_entry(e)
        if cat in cbct_and_none:
            continue
        by_cat.setdefault(cat, []).append(e)

    for category, entries in by_cat.items():
        # 4a) Podziel wpisy tej kategorii na klastry wg rzeczywistego sąsiedztwa
        clusters = cluster_by_tooth_neighborhood(entries)

        for group in clusters:
            # 4b) W każdej grupie sortujemy malejąco po czasie, aby wypełnić 120 min
            group_sorted = sorted(
                group,
                key=lambda e: duration_map.get(e['procedure_code'], 60),
                reverse=True
            )

            curr_group = []
            curr_time = 0
            for e in group_sorted:
                d = duration_map.get(e['procedure_code'], 60)
                if curr_time + d <= 120:
                    curr_group.append(e)
                    curr_time += d
                else:
                    # 4c) Zapiszemy wizytę z bieżącą curr_group
                    teeth_codes = [x['tooth_code'] for x in curr_group]
                    if category == "Gingiwoplastyka":
                        base_price = price_map.get(category, 0)
                        per_price = per_tooth_map.get(category, 0)
                        cnt = len(curr_group)
                        total_cost = base_price + cnt * per_price
                        visits.append({
                            "idx":        idx,
                            "label":      f"Wizyta {idx}",
                            "category":   category,
                            "unit_price": per_price,
                            "count":      cnt,
                            "teeth":      teeth_codes,
                            "minutes":    curr_time,
                            "base_cost":  total_cost,
                            "extra":      0
                        })
                    else:
                        unit_price = price_map.get(category, 0)
                        cnt = len(curr_group)
                        visits.append({
                            "idx":        idx,
                            "label":      f"Wizyta {idx}",
                            "category":   category,
                            "unit_price": unit_price,
                            "count":      cnt,
                            "teeth":      teeth_codes,
                            "minutes":    curr_time,
                            "base_cost":  cnt * unit_price,
                            "extra":      0
                        })
                    idx += 1
                    # Rozpoczynamy nową porcję od e
                    curr_group = [e]
                    curr_time = d

            # 4d) Po pętli: ostatnia porcja (≤ 120 min)
            if curr_group:
                teeth_codes = [x['tooth_code'] for x in curr_group]
                if category == "Gingiwoplastyka":
                    base_price = price_map.get(category, 0)
                    per_price = per_tooth_map.get(category, 0)
                    cnt = len(curr_group)
                    total_cost = base_price + cnt * per_price
                    visits.append({
                        "idx":        idx,
                        "label":      f"Wizyta {idx}",
                        "category":   category,
                        "unit_price": per_price,
                        "count":      cnt,
                        "teeth":      teeth_codes,
                        "minutes":    curr_time,
                        "base_cost":  total_cost,
                        "extra":      0
                    })
                else:
                    unit_price = price_map.get(category, 0)
                    cnt = len(curr_group)
                    visits.append({
                        "idx":        idx,
                        "label":      f"Wizyta {idx}",
                        "category":   category,
                        "unit_price": unit_price,
                        "count":      cnt,
                        "teeth":      teeth_codes,
                        "minutes":    curr_time,
                        "base_cost":  cnt * unit_price,
                        "extra":      0
                    })
                idx += 1

    return visits






def aggregate_plan(parsed_entries, price_map, desc_map, duration_map, per_tooth_map):
    # 1. Tworzymy domyślny słownik planu z kluczami wszystkich standardowych kategorii,
    #    włącznie z Gingiwoplastyką (z "times": [] bez naliczania kosztu na tym etapie).
    plan = {
        "Higienizacja": {
            "teeth": ["wszystkie zęby"],
            "cost": None,
            "description": desc_map.get("Higienizacja", "")
        },
        "Mikroskopowe leczenie odtwórcze": {
            "teeth": [], "cost": 0,
            "description": desc_map.get("Mikroskopowe leczenie odtwórcze", ""),
            "times": []
        },
        "Weryfikacja zębów po leczeniu kanałowym": {
            "teeth": [], "cost": 0,
            "description": desc_map.get("Weryfikacja zębów po leczeniu kanałowym", ""),
            "times": []
        },
        "Odbudowa protetyczna - nakład": {
            "teeth": [], "cost": 0,
            "description": desc_map.get("Odbudowa protetyczna - nakład", ""),
            "times": []
        },
        "Konsultacja implantologiczna celem odbudowy braku zęba": {
            "teeth": [], "cost": 0,
            "description": desc_map.get("Konsultacja implantologiczna celem odbudowy braku zęba", ""),
            "times": []
        },
        "Do usunięcia": {
            "teeth": [], "cost": 0,
            "description": desc_map.get("Do usunięcia", ""),
            "times": []
        },
        # === DODAJEMY tutaj Gingiwoplastykę z pustymi polami na zęby, times i cost (zerowe)
        "Gingiwoplastyka": {
            "teeth": [],       # lista kodów zębów
            "cost": 0,         # tutaj wstawimy dopiero po pętli
            "description": desc_map.get("Gingiwoplastyka", ""),
            "times": []        # lista czasów (opcjonalnie, jeśli duration_map zawiera czasy)
        }
    }

    # 2. Przechodzimy po każdym wpisie z parsed_entries
    for entry in parsed_entries:
        category, tooth_code = classify_entry(entry)
        if category is None:
            continue

        # Jeśli to kategoria, której wcześniej nie było w plan, dodajemy ją „ad hoc”
        if category not in plan:
            plan[category] = {
                "teeth": [],
                "cost": 0,
                "description": desc_map.get(category, ""),
                "times": []
            }

        # Dodajemy numer zęba do listy teeth
        plan[category]["teeth"].append(tooth_code)
        # Dodajemy czas procedury (jeśli jest) – duration_map kluczuje po pełnym kodzie np. "14 Gingiwoplastyka",
        # ale w wielu miejscach używamy tylko kodu zęba; tu zakładamy, że duration_map.get(tooth_code) zwraca czas lub None.
        plan[category]["times"].append(duration_map.get(f"{tooth_code} Gingiwoplastyka") or duration_map.get(tooth_code) or None)

        # === ZMIANA ===
        # Jeżeli kategoria NIE JEST „Gingiwoplastyka”, to doliczamy jednostkową cenę z price_map
        if category != "Gingiwoplastyka":
            plan[category]["cost"] += price_map.get(category, 0)

        # W przypadku Gingiwoplastyki NIE robimy tu nic – koszt policzymy po pętli na podstawie per_tooth_map i base
    # --- KONIEC PĘTLI ---

    # 3. Po wyjściu z pętli sprawdzamy, czy mamy w planie jakieś zęby do Gingiwoplastyki.
    gingi_teeth = plan["Gingiwoplastyka"]["teeth"]
    if gingi_teeth:
        base = price_map.get("Gingiwoplastyka", 0)
        per  = per_tooth_map.get("Gingiwoplastyka", 0)
        count = len(gingi_teeth)
        total = base + count * per

        plan["Gingiwoplastyka"]["cost"] = total
        plan["Gingiwoplastyka"]["cost_expr"] = f"{base} zł + {count} × {per} zł = {total} zł"

    return plan





def generate_treatment_plan(input_str, price_map, desc_map, duration_map, per_tooth_map):
    # 1) Sparsuj wejście
    parsed = parse_input(input_str)
    # 2) Zbuduj plan, przekazując mapy cen i opisów
    plan = aggregate_plan(parsed, price_map, desc_map, duration_map, per_tooth_map)
    # 3) Zwróć gotowy plan
    return plan


    # Opcjonalnie: Analiza podobieństwa semantycznego wprowadzonego tekstu
    similarity = analyze_treatment_similarity(input_str)  # funkcja zdefiniowana poniżej

    categories_order = [
        "Higienizacja",
        "Mikroskopowe leczenie odtwórcze",
        "Weryfikacja zębów po leczeniu kanałowym",
        "Odbudowa protetyczna - nakład",
        "Konsultacja implantologiczna celem odbudowy braku zęba",
        "Do usunięcia"
    ]

    output_lines = []
    point = 1
    output_lines.append(f"{point}. Higienizacja")
    point += 1

    for category in categories_order[1:]:
        items = plan[category]["teeth"]
        if items:
            output_lines.append(f"{point}. {category}:")
            for tooth in items:
                output_lines.append(f"- {tooth}")
            cost = plan[category]["cost"]
            if cost and category not in ["Konsultacja implantologiczna celem odbudowy braku zęba"]:
                if category in ["Mikroskopowe leczenie odtwórcze", "Weryfikacja zębów po leczeniu kanałowym"]:
                    output_lines.append(f"Łącznie {len(items)} x {treatment_prices[category]} zł = {cost} zł")
                elif category == "Odbudowa protetyczna - nakład":
                    output_lines.append(f"Łącznie {len(items)} x {treatment_prices[category]} zł = {cost} zł")
            elif category == "Konsultacja implantologiczna celem odbudowy braku zęba":
                output_lines.append("Koszt: 250 zł")
            point += 1

    # Dodajemy analizę podobieństwa (opcjonalnie, można zakomentować, gdy już nie potrzeba)
    output_lines.append("\nAnaliza podobieństwa semantycznego:")
    sim_str = "\n".join([f"{cat}: {sim:.2f}" for cat, sim in similarity.items()])
    output_lines.append(sim_str)

    return "\n".join(output_lines)

# … (inne importy i definicje) …

def tooth_description(code: str) -> str:
    """
    Zwraca opis położenia zęba wg schematu:
     - pierwsza cyfra: 1 = prawa górna, 2 = lewa górna, 3 = lewa dolna, 4 = prawa dolna
     - druga cyfra:  1–8 → kolejność: 1=jedynka, 2=dwójka, 3=trójka, 4=czwórka, 5=piątka, 6=szóstka, 7=siódemka, 8=ósemka
    Przykład: "14" → pierwsza cyfra 1 (“prawa górna”), druga cyfra 4 (“czwórka”) → "prawa górna czwórka"
    """
    quad_map = {
        "1": "prawa górna",
        "2": "lewa górna",
        "3": "lewa dolna",
        "4": "prawa dolna"
    }
    num_map = {
        "1": "jedynka",
        "2": "dwójka",
        "3": "trójka",
        "4": "czwórka",
        "5": "piątka",
        "6": "szóstka",
        "7": "siódemka",
        "8": "ósemka"
    }
    if len(code) != 2:
        return ""
    quad   = quad_map.get(code[0], "")
    number = num_map.get(code[1], "")
    return f"{quad} {number}" if quad and number else ""


def format_plan_as_text(plan, price_map):
    lines = ["Wygenerowany plan leczenia:", ""]
    idx = 1

    for category, data in plan.items():
        # Pomijamy „Higienizacja” lub kategorie bez zębów
        if category == "Higienizacja" or not data["teeth"]:
            continue

        # Nagłówek sekcji z kolejnym numerem
        lines.append(f"{idx}. {category}:")
        lines.append("")  # odstęp przed listą zębów

        # Dla Goniewoplastyki z opisem położenia
        if category == "Gingiwoplastyka":
            for tooth in data["teeth"]:
                desc = tooth_description(tooth)
                if desc:
                    lines.append(f"- {tooth} ({desc})")
                else:
                    lines.append(f"- {tooth}")
            lines.append("")

            full_expr = data.get("cost_expr", "").strip()
            if full_expr:
                parts     = full_expr.split("+", 1)
                base_part = parts[0].strip()
                rest_part = "+" + parts[1].strip()
                summary   = f"Łącznie: {base_part} (cena podstawowa) {rest_part}"
                lines.append(summary)
                lines.append("")

        else:
            # Pozostałe kategorie
            for tooth in data["teeth"]:
                desc = tooth_description(tooth)
                if desc:
                    lines.append(f"- {tooth} ({desc})")
                else:
                    lines.append(f"- {tooth}")
            lines.append("")

            if category == "Konsultacja implantologiczna celem odbudowy braku zęba":
                cost = price_map.get(category, 0)
                lines.append(f"Koszt: {cost} zł")
                lines.append("")
            else:
                count      = len(data["teeth"])
                unit_price = price_map.get(category, 0)
                total      = count * unit_price
                lines.append(f"Łącznie: {count} × {unit_price} zł = {total} zł")
                lines.append("")

        # Opcjonalnie: dodajemy opis, jeśli istnieje
        desc_text = data.get("description", "").strip()
        if desc_text:
            lines.append("")      # dodatkowy odstęp
            lines.append(desc_text)
            lines.append("")

        idx += 1

    return "\n".join(lines)




def analyze_treatment_similarity(input_text):
    """
    Oblicza kosinusową miarę podobieństwa między wprowadzonym tekstem a standardowymi kategoriami leczenia.
    Używamy TF-IDF do tokenizacji.
    """
    standard_categories = list(treatment_prices.keys())
    vectorizer = TfidfVectorizer()
    standard_vectors = vectorizer.fit_transform(standard_categories)
    input_vector = vectorizer.transform([input_text])
    similarities = cosine_similarity(input_vector, standard_vectors)
    return dict(zip(standard_categories, similarities[0]))

# Import dodatkowych funkcji z scikit-learn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# ---------------------------



def convert_docx_to_pages(docx_path: Path, pages_path: Path) -> bool:
    """
    macOS-only: używa textutil do konwersji .docx → .pages.
    Zwraca True jeśli się udało, False jeśli pominięto (nie-macOS) lub wystąpił błąd.
    """
    if sys.platform != "darwin":
        return False
    try:
        subprocess.run([
            "textutil", "-convert", "pages",
            str(docx_path), "-output", str(pages_path)
        ], check=True)
        return True
    except Exception as e:
        print(f"[WARN] textutil failed: {e}")
        return False

def create_word_doc(plan_text, clinic):
    doc = Document()
    styles = doc.styles
    normal = styles['Normal']
    normal.font.name = 'Century Gothic'
    # to na wypadek tekstów z wschodnioazjatycką czcionką
    normal._element.rPr.rFonts.set(qn('w:eastAsia'), 'Century Gothic')
    # i nagłówki
    for h in ['Heading 1','Heading 2','Heading 3']:
        st = styles[h]
        st.font.name = 'Century Gothic'
        st._element.rPr.rFonts.set(qn('w:eastAsia'), 'Century Gothic')
    # ——————————————————————————————————————————————————————

    # 1) Logo – wyśrodkowane
    if os.path.exists(clinic['logo_path']):
        p_logo = doc.add_paragraph()
        p_logo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r_logo = p_logo.add_run()
        r_logo.add_picture(clinic['logo_path'], width=Inches(1.5))

    # 2) Miejsce i data – wyrównane do prawej
    date_para = doc.add_paragraph()
    date_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    date_run = date_para.add_run(f"{clinic['city']} {datetime.now():%d.%m.%Y} r.")
    date_run.bold = True

    # 3) Dane lekarza i gabinetu – wyrównane do lewej
    info = (
        f"Lek. dent. {clinic['doctor_name']}\n"
        f"{clinic['clinic_name']}\n"
        f"{clinic['street']} {clinic['flat_number']}\n"
        f"{clinic['postal_code']} {clinic['city']}"
    )
    info_para = doc.add_paragraph(info)
    info_para.alignment = WD_ALIGN_PARAGRAPH.LEFT

    # 4) Tytuł – wyśrodkowany
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title_para.add_run("WSTĘPNY PLAN LECZENIA")
    run.bold = True
    run.font.size = Pt(14)
    doc.add_paragraph()  # odstęp

    # 5) Sekcje z plan_text
    lines    = plan_text.splitlines()
    sections = []
    current  = None

    for line in lines:
        m = re.match(r'^\d+\.\s*(.+?):\s*$', line)
        if m:
            if current:
                sections.append(current)
            current = {'category': m.group(1), 'lines': []}
        elif current and line.strip():
            current['lines'].append(line.strip())
    if current:
        sections.append(current)

    for sec in sections:
        cat = sec['category']
        doc.add_heading(cat.upper(), level=2)
        for ln in sec['lines']:
            if ln.startswith('- '):
                doc.add_paragraph(ln[2:], style='List Bullet')
            else:
                doc.add_paragraph(ln)
        doc.add_paragraph()  # odstęp między sekcjami

    # 6) Zwracamy BytesIO z gotowym .docx
    f = BytesIO()
    doc.save(f)
    f.seek(0)
    return f

@app.route("/download", methods=["POST"])
def download_docx():
    """
    Ściąga .docx – pełna implementacja.
    """
    # 1) Pobierz dane z formularza
    cabinet_id = request.form["cabinet_id"]
    input_data = request.form["input_data"].strip()
    cabinet    = Cabinet.query.get_or_404(cabinet_id)

    # 2) Zbuduj price_map, desc_map i per_tooth_map
    types         = TreatmentType.query.all()
    price_map     = {t.name: t.default_price       for t in types}
    desc_map      = {t.name: t.default_description for t in types}
    treatments    = Treatment.query.filter_by(cabinet_id=cabinet_id).all()
    per_tooth_map = {}

    for t in treatments:
        # zawsze nadpisujemy opis w przypadku indywidualnej konfiguracji
        desc_map[t.type] = t.description

        if t.type == "Gingiwoplastyka":
            # dla Gingiwoplastyki korzystamy z osobnych pól base_price i per_tooth_price
            price_map[t.type]      = t.base_price or 0
            per_tooth_map[t.type]  = t.per_tooth_price or 0
        else:
            # dla pozostałych rodzajów zabiegów korzystamy z pola price
            price_map[t.type]      = t.price or 0

    # 3) Zbuduj duration_map z ProcedureCode i ewentualnie nadpisz z Treatment.duration
    duration_map = {pc.code: pc.default_duration for pc in ProcedureCode.query.all()}
    for t in treatments:
        if t.duration is not None:
            # jeżeli lekarz wprowadził indywidualny czas dla zabiegu,
            # używamy identycznej nazwy procedury jako klucza:
            duration_map[f"{t.type}"] = t.duration

    # 4) Wygeneruj strukturę planu i sformatuj do tekstu
    plan      = generate_treatment_plan(input_data, price_map, desc_map, duration_map, per_tooth_map)
    plan_text = format_plan_as_text(plan, price_map)

    # 5) Przygotuj dane kliniki dla nagłówka .docx
    if cabinet.logo:
        logo_path = os.path.join(app.static_folder, "uploads", cabinet.logo)
    else:
        logo_path = os.path.join(app.static_folder, "Lottiimage.png")

    clinic = {
        "logo_path":   logo_path,
        "doctor_name": cabinet.doctor_name,
        "clinic_name": cabinet.name,
        "street":      cabinet.street,
        "flat_number": cabinet.flat_number,
        "postal_code": cabinet.postal_code,
        "city":        cabinet.city
    }

    # 6) Stwórz plik .docx i odeślij do klienta
    f = create_word_doc(plan_text, clinic)
    return send_file(
        f,
        as_attachment=True,
        download_name="plan_leczenia.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )




@app.route("/download_pages", methods=["POST"])
def download_pages():
    """
    Wersja „.pages” – wysyłamy dokładnie ten sam DOCX, ale z rozszerzeniem .pages.
    """
    # 1) Pobranie formularza jak w /download
    cabinet_id = request.form["cabinet_id"]
    input_data = request.form["input_data"].strip()
    cabinet    = Cabinet.query.get_or_404(cabinet_id)

    # 2) Zbuduj price_map, desc_map i duration_map tak samo jak w download()
    types      = TreatmentType.query.all()
    price_map  = {t.name: t.default_price       for t in types}
    desc_map   = {t.name: t.default_description for t in types}
    treatments = Treatment.query.filter_by(cabinet_id=cabinet_id).all()
    for t in treatments:
        price_map[t.type] = t.price
        desc_map[t.type]  = t.description
    duration_map = {pc.code: pc.default_duration for pc in ProcedureCode.query.all()}
    for t in treatments:
        if t.duration is not None:
            duration_map[t.code] = t.duration

    # 3) Generowanie planu i DOCX-a
    plan      = generate_treatment_plan(input_data, price_map, desc_map, duration_map)
    plan_text = format_plan_as_text(plan, price_map)
    logo_path = (os.path.join(app.static_folder, "uploads", cabinet.logo)
                 if cabinet.logo
                 else os.path.join(app.static_folder, "Lottiimage.png"))
    clinic    = {
        "logo_path":   logo_path,
        "doctor_name": cabinet.doctor_name,
        "clinic_name": cabinet.name,
        "street":      cabinet.street,
        "flat_number": cabinet.flat_number,
        "postal_code": cabinet.postal_code,
        "city":        cabinet.city
    }
    f = create_word_doc(plan_text, clinic)

    # 4) Wyślij ten sam strumień, ale z nazwą .pages i MIME dla Pages.app
    f.seek(0)
    return send_file(
        f,
        as_attachment=True,
        download_name="plan_leczenia.pages",
        mimetype="application/vnd.apple.pages"
    )

# === Przykład wywołania ===
# generate_and_offer_formats(plan_text, clinic)




# — pozostałe importy i definicje zostają bez zmian —

# ---------------------------
# ---------------------------
# GŁÓWNY SZABLON APLIKACJI WEBOWEJ (ChatLottie)
# ---------------------------
main_template = """<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <title>ChatLotti – Generowanie planu leczenia</title>

  <!-- 1. Bootstrap CSS -->
  <link
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
    rel="stylesheet">

  <!-- 2. Ikony -->
  <link
    href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.1.1/css/all.min.css"
    rel="stylesheet">

  <style>
    body {
      background: #f0f4f8;
      color: #33475b;
      padding-top: 1rem;
      padding-bottom: 2rem;
    }
    .navbar {
      background: #ffffffcc;
      box-shadow: 0 2px 8px rgba(0,0,0,0.05);
      backdrop-filter: blur(10px);
    }
    .navbar-brand, .nav-link {
      color: #33475b !important;
      font-weight: 500;
    }
    .hero {
      background: linear-gradient(135deg, #3b8beb 0%, #6fa4ff 100%);
      color: #fff;
      padding: 2.5rem;
      border-radius: .75rem;
      box-shadow: 0 4px 15px rgba(0,0,0,0.1);
      text-align: center;
      margin-bottom: 2rem;
    }
    .btn-rounded {
      border-radius: 50px;
      padding: .75rem 1.5rem;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
      transition: all .2s ease-in-out;
    }
    .btn-rounded:hover {
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }
    .card-custom {
      border: none;
      border-radius: .75rem;
      box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }
    pre.plan {
      background: #e9ecef;
      border-radius: .5rem;
      padding: 1rem;
      font-family: monospace;
      white-space: pre-wrap;
    }
  </style>
</head>

<body>
  <!-- Navbar -->
  <nav class="navbar navbar-expand-lg sticky-top mb-4">
    <div class="container">
      <a class="navbar-brand" href="/"><i class="fa-solid fa-tooth me-2"></i>ChatLotti</a>
      <div class="ms-auto">
        <a class="nav-link d-inline px-3" href="/admin/cabinets"><i class="fa-solid fa-hospital me-1"></i> Gabinety</a>
        <a class="nav-link d-inline px-3" href="/logout"><i class="fa-solid fa-right-from-bracket me-1"></i> Wyloguj</a>
      </div>
    </div>
  </nav>

  <!-- Hero -->
  <div class="container">
    <div class="hero">
      <h1 class="display-6"><i class="fa-solid fa-calendar-check me-2"></i>Generowanie planu leczenia</h1>
      <p class="lead">Wprowadź kody zabiegów, a system rozłoży je na optymalne wizyty.</p>
    </div>
  </div>

  <!-- Formularz i Wyniki -->
  <div class="container">
    <div class="row gy-4">
      <!-- Formularz -->
      <div class="col-lg-4">
        <div class="card card-custom p-4">
          <h5 class="mb-3"><i class="fa-solid fa-microscope me-2"></i>Nowy plan</h5>
          {% if not cabinets %}
            <div class="alert alert-warning">Brak gabinetów. Dodaj gabinet w zakładce „Gabinety”.</div>
          {% else %}
            <form method="post">
              <div class="mb-3">
                <label class="form-label" for="cabinet_id">Gabinet</label>
                {% if cabinets|length > 1 %}
                  <select class="form-select" id="cabinet_id" name="cabinet_id" required>
                    <option value="">-- wybierz --</option>
                    {% for c in cabinets %}
                      <option value="{{ c.id }}" {% if c.id==selected_id %}selected{% endif %}>
                        {{ c.name }}
                      </option>
                    {% endfor %}
                  </select>
                {% else %}
                  <input type="hidden" name="cabinet_id" value="{{ cabinets[0].id }}">
                  <p class="form-control-plaintext"><strong>{{ cabinets[0].name }}</strong></p>
                {% endif %}
              </div>
              <div class="mb-3">
                <label class="form-label" for="input_data">Kody zabiegów</label>
                <textarea
                  class="form-control"
                  id="input_data"
                  name="input_data"
                  rows="4"
                  placeholder="np. 13 MOD, 14 MO">{{ input_data }}</textarea>
              </div>
              {% if error %}
                <div class="alert alert-danger">{{ error }}</div>
              {% endif %}
              <button type="submit" class="btn btn-primary btn-rounded w-100">
                <i class="fa-solid fa-magic me-1"></i> Generuj plan
              </button>
            </form>
          {% endif %}
        </div>
      </div>

      <!-- Wyniki -->
      <div class="col-lg-8">
        {% if result %}
          <div class="card card-custom mb-4">
            <div class="card-body">
              <h5 class="card-title"><i class="fa-solid fa-file-lines me-2"></i>Wygenerowany plan leczenia</h5>
              <pre class="plan">
{% for category, data in result_items if category != "Higienizacja" and data.teeth %}
{{ loop.index }}. {{ category }}
{% for tooth, time in data['items'] %}
- {{ tooth }}{% if time %} ({{ time }} min){% endif %}
{% endfor %}

{% if category == "Gingiwoplastyka" %}
Łącznie: {{ data.cost_expr }}
{% elif category == "Konsultacja implantologiczna celem odbudowy braku zęba" %}
Koszt: {{ price_map.get(category,0)|int }} zł
{% else %}
{% set count = data.teeth|length %}
Łącznie {{ count }} x {{ price_map.get(category,0)|int }} zł = {{ count * price_map.get(category,0)|int }} zł
{% endif %}

{% endfor %}
</pre>



    <div class="d-flex gap-2 mt-3">
      <form method="POST" action="/download" style="margin-right:1rem;">
        <input type="hidden" name="input_data" value="{{ input_data }}">
        <input type="hidden" name="cabinet_id"  value="{{ selected_id }}">
        <button class="btn btn-outline-secondary btn-rounded">
          <i class="fa-solid fa-download me-1"></i> Pobierz (.docx)
        </button>
      </form>

      <!--
      <form method="POST" action="/download_pages">
        <input type="hidden" name="input_data" value="{{ input_data }}">
        <input type="hidden" name="cabinet_id"  value="{{ selected_id }}">
        <button class="btn btn-outline-secondary btn-rounded">
          <i class="fa-solid fa-download me-1"></i> Pobierz (.pages)
        </button>
      </form>
      -->
    </div>



            </div>
          </div>
        {% endif %}

      {% if visits %}
  <div class="card card-custom mb-4">
    <div class="card-body">
      <h5 class="card-title">
        <i class="fa-solid fa-calendar-days me-2"></i>Harmonogram wizyt
      </h5>
      <ol class="ps-3">
        {% for v in visits %}
          {% set h = v.minutes // 60 %}
          {% set m = v.minutes % 60 %}

          {% if v.category == "Higienizacja" %}
            <li class="mb-3">
              <strong>Wizyta {{ h }}h {{ m }}min</strong> – Higienizacja.
            </li>
          {% else %}
            {% set teeth_list = v.teeth | join(' i ') %}
            {% if v.category == "Odbudowa protetyczna - nakład" %}
              {% set extra_lbl = " (odbudowa tymczasowa)" %}
            {% else %}
              {% set extra_lbl = "" %}
            {% endif %}

            {# Budujemy opis kosztów #}
            {% if v.extra == 0 and v.count > 1 %}
              {# wszystkie zęby tej samej kategorii #}
              {% set cost_desc = v.count ~ " x " ~ v.unit_price ~ " zł = " ~ v.base_cost ~ " zł" %}
            {% else %}
              {# mieszane kategorie lub tylko jeden #}
              {% set parts = [] %}
              {% for tooth in v.teeth %}
                {# dla uproszczenia: każda pozycja 1 × unit_price #}
                {% set parts = parts + ["1 x " ~ v.unit_price ~ " zł"] %}
              {% endfor %}
              {% set cost_desc = parts | join(" + ") ~ " = " ~ v.base_cost ~ " zł" %}
            {% endif %}

            <li class="mb-3">
              <strong>Wizyta {{ h }}h {{ m }}min</strong>
              – leczenie zęba {{ teeth_list }}{{ extra_lbl }}.
              Przewidywany koszt wizyty to {{ cost_desc }}.
            </li>
          {% endif %}
        {% endfor %}
      </ol>
    </div>
  </div>
{% endif %}

  <!-- Bootstrap JS Bundle -->
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""
plans_list_template = """
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <title>Wygenerowane plany</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.1.1/css/all.min.css" rel="stylesheet">
  <style>
    body { background: #f0f4f8; color: #33475b; padding-top: 1rem; padding-bottom: 2rem; }
    .navbar { background: #ffffffcc; box-shadow: 0 2px 8px rgba(0,0,0,0.05); backdrop-filter: blur(10px); }
    .btn-rounded { border-radius: 50px; padding: .5rem 1.25rem; transition: all .2s ease-in-out; }
    .btn-rounded:hover { transform: translateY(-2px); }
    .card-custom { border: none; border-radius: .75rem; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }
  </style>
</head>
<body>
  <!-- Navbar (możesz skopiować ten sam, co w main_template) -->
  <nav class="navbar navbar-expand-lg sticky-top mb-4">
    <div class="container">
      <a class="navbar-brand" href="/"><i class="fa-solid fa-tooth me-2"></i>ChatLotti</a>
      <div class="ms-auto">
        <a class="nav-link d-inline px-3" href="/plans"><i class="fa-solid fa-file-alt me-1"></i> Wygenerowane plany</a>
        <a class="nav-link d-inline px-3" href="/admin/cabinets"><i class="fa-solid fa-hospital me-1"></i> Gabinety</a>
        <a class="nav-link d-inline px-3" href="/logout"><i class="fa-solid fa-right-from-bracket me-1"></i> Wyloguj</a>
      </div>
    </div>
  </nav>

  <div class="container">
    <div class="card card-custom mb-4">
      <div class="card-body">
        <h5 class="card-title"><i class="fa-solid fa-list me-2"></i>Wygenerowane plany</h5>
        {% if not plans %}
          <div class="alert alert-warning">Brak zapisanych planów.</div>
        {% else %}
          <table class="table table-hover">
            <thead class="table-light">
              <tr>
                <th>#</th>
                <th>Data i godzina</th>
                <th>Gabinet</th>
                <th>Input (skrócone)</th>
                <th>Akcje</th>
              </tr>
            </thead>
            <tbody>
              {% for p in plans %}
                <tr>
                  <td>{{ loop.index }}</td>
                  <td>{{ p.created_at.strftime("%d.%m.%Y %H:%M:%S") }}</td>
                  <td>{{ p.cabinet.name }}</td>
                  <td style="max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                    {{ p.input_data }}
                  </td>
                  <td>
                    <a href="{{ url_for('view_or_edit_plan', plan_id=p.id) }}"
                       class="btn btn-sm btn-primary btn-rounded me-1">
                      <i class="fa-solid fa-eye me-1"></i>Podgląd / Edytuj
                    </a>
                    <form method="POST"
                          action="{{ url_for('delete_plan', plan_id=p.id) }}"
                          style="display:inline;"
                          onsubmit="return confirm('Czy na pewno usunąć ten plan?');">
                      <button type="submit" class="btn btn-sm btn-danger btn-rounded">
                        <i class="fa-solid fa-trash me-1"></i>Usuń
                      </button>
                    </form>
                  </td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        {% endif %}
      </div>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""
plan_detail_template = """
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <title>Podgląd / Edytuj plan leczenia</title>

  <!-- Bootstrap CSS -->
  <link
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
    rel="stylesheet">
  <!-- FontAwesome -->
  <link
    href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.1.1/css/all.min.css"
    rel="stylesheet">
  <style>
    body {
      background: #f0f4f8;
      color: #33475b;
      padding-top: 1rem;
      padding-bottom: 2rem;
    }
    .navbar {
      background: #ffffffcc;
      box-shadow: 0 2px 8px rgba(0,0,0,0.05);
      backdrop-filter: blur(10px);
    }
    .navbar-brand, .nav-link {
      color: #33475b !important;
      font-weight: 500;
    }
    .hero {
      background: linear-gradient(135deg, #3b8beb 0%, #6fa4ff 100%);
      color: #fff;
      padding: 2.5rem;
      border-radius: .75rem;
      box-shadow: 0 4px 15px rgba(0,0,0,0.1);
      text-align: center;
      margin-bottom: 2rem;
    }
    .btn-rounded {
      border-radius: 50px;
      padding: .75rem 1.5rem;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
      transition: all .2s ease-in-out;
    }
    .btn-rounded:hover {
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    }
    .card-custom {
      border: none;
      border-radius: .75rem;
      box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }
    pre.plan {
      background: #e9ecef;
      border-radius: .5rem;
      padding: 1rem;
      font-family: monospace;
      white-space: pre-wrap;
    }
  </style>
</head>

<body>
  <!-- Navbar -->
  <nav class="navbar navbar-expand-lg sticky-top mb-4">
    <div class="container">
      <a class="navbar-brand" href="/"><i class="fa-solid fa-tooth me-2"></i>ChatLotti</a>
      <div class="ms-auto">
        <a class="nav-link d-inline px-3" href="/plans"><i class="fa-solid fa-file-alt me-1"></i>Wygenerowane plany</a>
        <a class="nav-link d-inline px-3" href="/"><i class="fa-solid fa-calendar-check me-1"></i>Generuj plan</a>
        <a class="nav-link d-inline px-3" href="/admin/cabinets"><i class="fa-solid fa-hospital me-1"></i>Gabinety</a>
        <a class="nav-link d-inline px-3" href="/logout"><i class="fa-solid fa-right-from-bracket me-1"></i>Wyloguj</a>
      </div>
    </div>
  </nav>

  <!-- Hero -->
  <div class="container">
    <div class="hero">
      <h1 class="display-6"><i class="fa-solid fa-file-alt me-2"></i>Podgląd / Edytuj plan</h1>
      <p class="lead">Możesz zmienić kody zabiegów i ponownie wygenerować plan leczenia.</p>
    </div>
  </div>

  <div class="container">
    <div class="row gy-4">
      <!-- Formularz edycji -->
      <div class="col-lg-4">
        <div class="card card-custom p-4">
          <h5 class="mb-3"><i class="fa-solid fa-pen-to-square me-2"></i>Edytuj plan</h5>
          <form method="post" action="/plans/{{ plan.id }}">
            <!-- Ukryte pole z gabinetem (nie chcemy, aby użytkownik go zmieniał) -->
            <input type="hidden" name="cabinet_id" value="{{ plan.cabinet_id }}">

            <div class="mb-3">
              <label class="form-label" for="input_data">Kody zabiegów</label>
              <textarea
                class="form-control"
                id="input_data"
                name="input_data"
                rows="4"
                required>{{ plan.input_data }}</textarea>
            </div>

            <button type="submit" class="btn btn-primary btn-rounded w-100">
              <i class="fa-solid fa-magic me-1"></i> Zaktualizuj plan
            </button>
          </form>
        </div>
      </div>

      <!-- Wyniki (istniejący plan + harmonogram) -->
      <div class="col-lg-8">
        {% if result %}
          <div class="card card-custom mb-4">
            <div class="card-body">
              <h5 class="card-title"><i class="fa-solid fa-file-lines me-2"></i>Wygenerowany plan leczenia</h5>
              <pre class="plan">1. Higienizacja
{% for category, data in result_items if category != "Higienizacja" and data.teeth %}
{{ loop.index + 1 }}. {{ category }}
{% for tooth, time in data['items'] %}
- {{ tooth }}
{% endfor %}

{% if category == "Gingiwoplastyka" %}
Łącznie: {{ data.cost_expr }}
{% elif category == "Konsultacja implantologiczna celem odbudowy braku zęba" %}
Koszt: {{ price_map.get(category,0)|int }} zł
{% else %}
{% set count = data.teeth|length %}
Łącznie {{ count }} x {{ price_map.get(category,0)|int }} zł = {{ count * price_map.get(category,0)|int }} zł
{% endif %}

{% endfor %}</pre>
            </div>
          </div>
        {% endif %}

        {% if visits %}
          <div class="card card-custom mb-4">
            <div class="card-body">
              <h5 class="card-title">
                <i class="fa-solid fa-calendar-days me-2"></i>Harmonogram wizyt
              </h5>
              <ol class="ps-3">
                {% for v in visits %}
                  {% set h = v.minutes // 60 %}
                  {% set m = v.minutes % 60 %}
                  {% if v.category == "Higienizacja" %}
                    <li class="mb-3">
                      <strong>Wizyta {{ h }}h {{ m }}min</strong> – Higienizacja.
                    </li>
                  {% else %}
                    {% set teeth_list = v.teeth | join(' i ') %}
                    {% if v.category == "Odbudowa protetyczna - nakład" %}
                      {% set extra_lbl = " (odbudowa tymczasowa)" %}
                    {% else %}
                      {% set extra_lbl = "" %}
                    {% endif %}

                    {# Budujemy opis kosztów #}
                    {% if v.extra == 0 and v.count > 1 %}
                      {% set cost_desc = v.count ~ " x " ~ v.unit_price ~ " zł = " ~ v.base_cost ~ " zł" %}
                    {% else %}
                      {% set parts = [] %}
                      {% for tooth in v.teeth %}
                        {% set parts = parts + ["1 x " ~ v.unit_price ~ " zł"] %}
                      {% endfor %}
                      {% set cost_desc = parts | join(" + ") ~ " = " ~ v.base_cost ~ " zł" %}
                    {% endif %}

                    <li class="mb-3">
                      <strong>Wizyta {{ h }}h {{ m }}min</strong>
                      – leczenie zęba {{ teeth_list }}{{ extra_lbl }}.
                      Przewidywany koszt wizyty to {{ cost_desc }}.
                    </li>
                  {% endif %}
                {% endfor %}
              </ol>
            </div>
          </div>
        {% endif %}

        <!-- Przyciski akcji: Pobierz Word -->
        <div class="d-flex gap-2 mt-3">
          <form method="POST" action="/download" style="margin-right:1rem;">
            <input type="hidden" name="cabinet_id" value="{{ plan.cabinet_id }}">
            <input type="hidden" name="input_data" value="{{ plan.input_data }}">
            <button class="btn btn-outline-secondary btn-rounded">
              <i class="fa-solid fa-download me-1"></i> Pobierz (.docx)
            </button>
          </form>
        </div>

      </div>
    </div>
  </div>

  <!-- Bootstrap JS Bundle -->
  <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""



@app.route("/", methods=["GET", "POST"])
def index():
    all_cabinets = Cabinet.query.filter_by(user_id=session["user_id"]).all()

    input_data  = ""
    result      = {}
    visits      = []
    error       = ""
    selected_id = None

    # 1) Pobierz globalne ceny i opisy z TreatmentType
    types     = TreatmentType.query.all()
    price_map = {t.name: t.default_price       for t in types}
    desc_map  = {t.name: t.default_description for t in types}

    # 2) Pobierz domyślne czasy z ProcedureCode
    duration_map = {
        pc.code: pc.default_duration
        for pc in ProcedureCode.query.all()
    }

    if request.method == "POST":
        selected_id = request.form.get("cabinet_id")
        input_data  = request.form.get("input_data", "").strip()

        # Walidacja wyboru gabinetu
        if not all_cabinets:
            error = "Brak gabinetów. Dodaj gabinet w zakładce Gabinety."
        elif len(all_cabinets) > 1 and not selected_id:
            error = "Proszę wybrać gabinet z listy."
        else:
            # Jeśli jest tylko jeden gabinet, ustawiamy go automatycznie
            if len(all_cabinets) == 1:
                selected_id = all_cabinets[0].id

            # Pobieramy wszystkie istniejące Treatment i CodeDuration dla wybranego gabinetu
            treatments = Treatment.query.filter_by(cabinet_id=selected_id).all()
            cds        = CodeDuration.query.filter_by(cabinet_id=selected_id).all()

            # 3) Nadpisanie duration_map na podstawie CodeDuration (trimmed mean 10%)
            from collections import defaultdict
            by_code = defaultdict(list)
            for cd in cds:
                by_code[cd.procedure_code].append(cd.duration)
            for proc_code, lst in by_code.items():
                ds      = sorted(lst)
                n       = len(ds)
                trim    = int(n * 0.1)
                trimmed = ds[trim : n - trim] or ds
                optimal = sum(trimmed) // len(trimmed)
                duration_map[proc_code] = optimal

            # 4) Nadpisanie cen i opisów per gabinet + budowa per_tooth_map dla Gingiwoplastyki
            per_tooth_map = {}
            for t in treatments:
                # opis zawsze nadpisujemy
                desc_map[t.type] = t.description or ""
                if t.type == "Gingiwoplastyka":
                    # dla Gingiwoplastyki używamy base_price i per_tooth_price
                    price_map[t.type]      = t.base_price or 0
                    per_tooth_map[t.type]  = t.per_tooth_price or 0
                else:
                    # wszystkie pozostałe zabiegi korzystają z pola price
                    price_map[t.type]      = t.price or 0

            # 5) Wygeneruj plan i harmonogram, jeśli jest input_data
        if input_data:
            # 1) Generujemy słownik planu leczenia
            result = generate_treatment_plan(
                input_data,
                price_map,
                desc_map,
                duration_map,
                per_tooth_map
            )

            # 2) Budujemy harmonogram wizyt (lista słowników)
            parsed = parse_input(input_data)
            visits = generate_visit_plan(parsed, duration_map, price_map, per_tooth_map)

            # 3) Tworzymy tekstowy output planu (formatowanie do łańcucha)
            plan_text = format_plan_as_text(result, price_map)

            # 4) Zapisujemy do bazy nowy rekord GeneratedPlan
            new_plan = GeneratedPlan(
                user_id    = session["user_id"],
                cabinet_id = selected_id,
                input_data = input_data,
                plan_text  = plan_text
            )
            db.session.add(new_plan)
            db.session.commit()

        else:
            visits = []


    # Przygotuj result_items do pętli w szablonie
    result_items = []
    for cat, data in result.items():
        teeth = data.get("teeth", [])
        times = data.get("times", [])
        data["items"] = list(zip(teeth, times))
        result_items.append((cat, data))

    return render_template_string(
        main_template,
        cabinets     = all_cabinets,
        input_data   = input_data,
        result       = result,
        result_items = result_items,
        visits       = visits,
        error        = error,
        selected_id  = selected_id,
        price_map    = price_map,
        duration_map = duration_map
    )

@app.route("/plans")
def list_generated_plans():
    # Pobieramy tylko plany zalogowanego usera
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    plans = GeneratedPlan.query.filter_by(user_id=user_id).order_by(GeneratedPlan.created_at.desc()).all()
    return render_template_string(
        plans_list_template,
        plans = plans
    )
@app.route("/plans/<int:plan_id>", methods=["GET", "POST"])
def view_or_edit_plan(plan_id):
    plan = GeneratedPlan.query.get_or_404(plan_id)

    # Tylko właściciel może edytować/podglądać
    if plan.user_id != session.get("user_id"):
        return redirect(url_for("list_generated_plans"))

    # --- Przygotowanie map cen/opisów/czasów jak w index() ---
    # 1) Pobierz wszystkie typy zabiegów
    types = TreatmentType.query.all()
    price_map = {t.name: t.default_price for t in types}
    desc_map = {t.name: t.default_description for t in types}

    # 2) Pobierz wszystkie „Treatment” dla danego gabinetu, by nadpisać price_map/desć_map/per_tooth_map
    treatments_db = Treatment.query.filter_by(cabinet_id=plan.cabinet_id).all()

    per_tooth_map = {}
    for t in treatments_db:
        # zawsze nadpisujemy opis
        desc_map[t.type] = t.description or ""
        if t.type == "Gingiwoplastyka":
            price_map[t.type] = t.base_price or 0
            per_tooth_map[t.type] = t.per_tooth_price or 0
        else:
            price_map[t.type] = t.price or 0

    # 3) Budujemy duration_map:
    duration_map = {pc.code: pc.default_duration for pc in ProcedureCode.query.all()}
    for t in treatments_db:
        if t.duration is not None:
            # gdy leczenie ma własny czas, kluczujemy po pełnym PCercategory
            # (w main_template i indexie trzeba mieć spójność – tu przyjmujemy, że t.code to istniejący PCercategory)
            duration_map[t.code] = t.duration

    # --- Jeżeli POST: aktualizujemy rekord i generujemy nowe result/visits ---
    if request.method == "POST":
        new_input = request.form.get("input_data", "").strip()
        if new_input:
            # 1) Generujemy nowy plan i harmonogram
            parsed = parse_input(new_input)
            new_result = generate_treatment_plan(new_input, price_map, desc_map, duration_map, per_tooth_map)
            new_visits = generate_visit_plan(parsed, duration_map, price_map, per_tooth_map)

            # 2) Tworzymy nowy tekstowy output planu
            new_plan_text = format_plan_as_text(new_result, price_map)

            # 3) Nadpisujemy w bazie
            plan.input_data = new_input
            plan.plan_text = new_plan_text
            plan.created_at = datetime.utcnow()
            db.session.commit()

        # Po aktualizacji przenosimy np. na listę wygenerowanych planów
        return redirect(url_for("list_generated_plans"))

    # --- GET: wyświetlamy istniejący plan w postaci szablonu i generujemy result/visits ---
    # Używamy plan.input_data do odtworzenia result/visits
    parsed = parse_input(plan.input_data)
    result = generate_treatment_plan(plan.input_data, price_map, desc_map, duration_map, per_tooth_map)
    visits = generate_visit_plan(parsed, duration_map, price_map, per_tooth_map)

    # Przygotuj result_items tak, jak w index()
    result_items = []
    for cat, data in result.items():
        teeth = data.get("teeth", [])
        times = data.get("times", [])
        data["items"] = list(zip(teeth, times))
        result_items.append((cat, data))

    return render_template_string(
        plan_detail_template,
        plan = plan,
        selected_id = plan.cabinet_id,
        input_data = plan.input_data,
        result = result,
        result_items = result_items,
        visits = visits,
        price_map = price_map,
        duration_map = duration_map
    )

@app.route("/plans/<int:plan_id>/delete", methods=["POST"])
def delete_plan(plan_id):
    plan = GeneratedPlan.query.get_or_404(plan_id)
    # upewnijmy się, że tylko właściciel może usuwać
    if plan.user_id != session.get("user_id"):
        return redirect(url_for("list_generated_plans"))
    db.session.delete(plan)
    db.session.commit()
    return redirect(url_for("list_generated_plans"))


@app.route("/download", methods=["POST"])
def download():
    cabinet_id = request.form.get("cabinet_id")
    input_data = request.form.get("input_data", "").strip()

    # 1) Pobierz cabinet i zabiegi
    cabinet = Cabinet.query.get_or_404(cabinet_id)
    treatments = Treatment.query.filter_by(cabinet_id=cabinet_id).all()

    # 2) Zbuduj price_map i desc_map tak samo jak w index()
    types     = TreatmentType.query.all()
    price_map = {t.name: t.default_price for t in types}
    desc_map  = {t.name: t.default_description for t in types}
    for t in treatments:
        price_map[t.type] = t.price
        desc_map[t.type]  = t.description
    # 3) Zbuduj mapę domyślnych czasów (tak jak w index)
    duration_map = {
        pc.code: pc.default_duration
        for pc in ProcedureCode.query.all()
    }
    # (opcjonalnie) możesz nadpisać czasy z bazy Treatment, gdy leczenia mają własne czasy:
    for t in treatments:
        if t.duration is not None:
            # tutaj użyj odpowiedniego klucza.
            # Jeśli chcesz nadpisywać na podstawie kodu procedury,
            # upewnij się, że masz t.code;
            # albo pomiń tę sekcję, jeśli nie potrzebujesz nadpisywać.
            duration_map[t.code] = t.duration


    # 3) Wygeneruj słownik planu
    plan = generate_treatment_plan(input_data, price_map, desc_map, duration_map)

    # 4) Sformatuj go do tekstu
    plan_text = format_plan_as_text(plan, price_map)

    # 5) Przygotuj dane kliniki
    if cabinet.logo:
        logo_path = os.path.join(app.static_folder, "uploads", cabinet.logo)
    else:
        logo_path = os.path.join(app.static_folder, "Lottiimage.png")

    clinic = {
        "logo_path":   logo_path,
        "doctor_name": cabinet.doctor_name,
        "clinic_name": cabinet.name,
        "street":      cabinet.street,
        "flat_number": cabinet.flat_number,
        "postal_code": cabinet.postal_code,
        "city":        cabinet.city
    }

    # 6) Generuj i wyślij Worda
    f = create_word_doc(plan_text, clinic)
    return send_file(
        f,
        as_attachment=True,
        download_name="plan_leczenia.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )



@app.route("/admin", methods=["GET", "POST"])
def admin():
    global treatment_prices, treatment_descriptions
    message = ""
    if request.method == "POST":
        try:
            # aktualizacja cen
            treatment_prices["Mikroskopowe leczenie odtwórcze"] = int(request.form["mikro"])
            treatment_prices["Weryfikacja zębów po leczeniu kanałowym"] = int(request.form["endo"])
            treatment_prices["Odbudowa protetyczna - nakład"] = int(request.form["naklad"])
            treatment_prices["Konsultacja implantologiczna celem odbudowy braku zęba"] = int(request.form["implant"])
            # aktualizacja opisów
            treatment_descriptions["Mikroskopowe leczenie odtwórcze"] = request.form["desc_mikro"].strip()
            treatment_descriptions["Weryfikacja zębów po leczeniu kanałowym"] = request.form["desc_endo"].strip()
            treatment_descriptions["Odbudowa protetyczna - nakład"] = request.form["desc_naklad"].strip()
            treatment_descriptions["Konsultacja implantologiczna celem odbudowy braku zęba"] = request.form["desc_implant"].strip()
            message = "Ceny i opisy zostały zaktualizowane."
        except Exception as e:
            message = f"Błąd podczas zapisu: {e}"
    return render_template_string(
        admin_template,
        prices=treatment_prices,
        descriptions=treatment_descriptions,
        message=message
    )
@app.route("/admin/cabinets", methods=["GET", "POST"])
def admin_cabinets():
    message = ""
    if request.method == "POST":
        # 1) Pobierz pola z formularza
        name        = request.form["name"].strip()
        logo_file   = request.files.get("logo")
        doctor_name = request.form["doctor_name"].strip()
        street      = request.form["street"].strip()
        flat_number = request.form["flat_number"].strip()
        postal_code = request.form["postal_code"].strip()
        city        = request.form["city"].strip()

        # 2) Obsługa uploadu logo (jeśli jest)
        logo_filename = None
        if logo_file and logo_file.filename:
            logo_filename = f"{uuid.uuid4().hex}_{secure_filename(logo_file.filename)}"
            logo_file.save(os.path.join(UPLOAD_FOLDER, logo_filename))

        # 3) Zapis do bazy
        cab = Cabinet(
            name        = name,
            logo        = logo_filename,
            doctor_name = doctor_name,
            street      = street,
            flat_number = flat_number,
            postal_code = postal_code,
            city        = city,
            user_id     = session["user_id"]
        )
        db.session.add(cab)
        db.session.commit()
        message = f"Gabinet „{name}” został dodany."

    # 4) Pobierz wszystkie gabinety zalogowanego użytkownika
    cabinets = Cabinet.query.filter_by(user_id=session["user_id"]).all()

    # 5) Renderuj szablon
    return render_template_string(
        cabinets_template,
        cabinets=cabinets,
        message=message
    )

@app.route("/admin/cabinets/<cabinet_id>/treatments", methods=["GET", "POST"])
def admin_treatments(cabinet_id):
    # 1) Pobierz gabinet lub zwróć 404
    cabinet = Cabinet.query.get_or_404(cabinet_id)
    message = ""

    # 2) Pobierz listę typów do dropdowna
    types = TreatmentType.query.all()

    # 3) Obsługa POST: zapis zabiegu na podstawie formularza
    if request.method == "POST":
       chosen_name = request.form["type"]
       description = request.form["description"].strip()
       tr = Treatment(cabinet_id=cabinet.id, type=chosen_name, description=description)

       if chosen_name == "Gingiwoplastyka":
           tr.base_price      = float(request.form["base_price"])
           tr.per_tooth_price = float(request.form["per_tooth_price"])
       else:
           tr.price = float(request.form["price"])

       db.session.add(tr)
       db.session.commit()
       message = f"Zabieg „{chosen_name}” dodany."


    # 4) Pobierz wszystkie zabiegi z bazy
    treatments = Treatment.query.filter_by(cabinet_id=cabinet.id).all()

    # 5) Renderuj szablon z dynamicznymi polami
    return render_template_string(
        treatments_template,
        cabinet    = cabinet,
        treatments = treatments,
        types      = types,
        message    = message
    )


@app.route("/admin/cabinets/<cabinet_id>/treatments/<treatment_id>/delete", methods=["POST"])
def delete_treatment(cabinet_id, treatment_id):
    # 1) Pobierz gabinet oraz wybranego zabiegu lub zwróć 404, jeśli nie istnieją
    cabinet = Cabinet.query.get_or_404(cabinet_id)
    tr = Treatment.query.filter_by(id=treatment_id, cabinet_id=cabinet.id).first_or_404()

    # 2) Usuń obiekt z bazy
    db.session.delete(tr)
    db.session.commit()

    # 3) Przekieruj z powrotem na listę zabiegów tego gabinetu
    return redirect(url_for("admin_treatments", cabinet_id=cabinet.id))

@app.route("/admin/cabinets/<cabinet_id>/treatments/<treatment_id>/edit", methods=["GET", "POST"])
def edit_treatment(cabinet_id, treatment_id):
    cabinet = Cabinet.query.get_or_404(cabinet_id)
    tr = Treatment.query.filter_by(id=treatment_id, cabinet_id=cabinet.id).first_or_404()
    if request.method == "POST":
        tr.description = request.form["description"].strip()
        tr.price       = float(request.form["price"])
        db.session.commit()
        return redirect(url_for("admin_treatments", cabinet_id=cabinet.id))
    return render_template_string(edit_treatment_template,
                                  cabinet=cabinet,
                                  treatment=tr)

@app.route("/admin/cabinets/<cabinet_id>/treatments/<treatment_id>/durations", methods=["GET", "POST"])
def add_duration(cabinet_id, treatment_id):
    cabinet   = Cabinet.query.get_or_404(cabinet_id)
    treatment = Treatment.query.filter_by(id=treatment_id, cabinet_id=cabinet.id).first_or_404()

    # 1) Pobieramy WSZYSTKIE wpisy CodeDuration tego gabinetu (posortowane malejąco po timestamp)
    all_durations = (
        CodeDuration
        .query
        .filter_by(cabinet_id=cabinet.id)
        .order_by(CodeDuration.timestamp.desc())
        .all()
    )

    # 2) „Seedowane” kody z tabeli ProcedureCode dla tej kategorii
    seeded = [
        pc.code
        for pc in ProcedureCode.query.filter_by(category_name=treatment.type).all()
    ]
    # Jeśli nie ma żadnego wpisu w ProcedureCode dla tej kategorii, wstawiamy samą nazwę zabiegu
    if not seeded:
        seeded = [treatment.type]

    # 3) Budujemy listę wpisów historycznych, ale tak, żeby również złapać
    #    te ręcznie wpisane „XX YYY” które klasyfikują się do tego typu zabiegu.
    history_entries = []
    for entry in all_durations:
        if treatment.type == "Gingiwoplastyka":
            # dla gingi: łapiemy wszystkie, których procedure_code kończy się na "Gingiwoplastyka"
            if entry.procedure_code.strip().endswith("Gingiwoplastyka"):
                history_entries.append(entry)
        else:
            # Dla innych zabiegów: spróbujmy rozbić procedure_code na „tooth” i „kod procedury”:
            m = re.match(r"^(\d{2})\s+(.+)$", entry.procedure_code)
            if m:
                tooth_code    = m.group(1)
                proc_short    = m.group(2).strip()
                # używamy classify_entry, żeby sprawdzić kategorię:
                cat, _ = classify_entry({
                    "tooth_code":     tooth_code,
                    "treatment_code": proc_short
                })
                if cat == treatment.type:
                    history_entries.append(entry)
            else:
                # Jeżeli procedure_code to np. dokładnie sama nazwa zabiegu (fallback)
                if entry.procedure_code == treatment.type:
                    history_entries.append(entry)

    # 4) Grupujemy je po dokładnym procedure_code (żeby zebrać wszystkie czasy dla tego samego numeru)
    from collections import defaultdict
    grouped = defaultdict(list)
    for e in history_entries:
        grouped[e.procedure_code].append(e)

    # 5) Tworzymy „history_groups” do szablonu (lista słowników)
    history_groups = []
    for proc_code, entries in grouped.items():
        # Spróbujmy pobrać obiekt ProcedureCode; jeśli nie ma, za kategorię bierzemy treatment.type
        pc_obj = ProcedureCode.query.get(proc_code)
        if pc_obj:
            category_name = pc_obj.category_name
        else:
            category_name = treatment.type

        durations_list_for_code = [e.duration for e in entries]
        # Obliczamy trimmed mean 10%
        ds = sorted(durations_list_for_code)
        n  = len(ds)
        low  = int(n * 0.1)
        high = n - low
        trimmed = ds[low:high] or ds
        optimal_for_this_code = int(sum(trimmed) / len(trimmed))

        history_groups.append({
            "category":       category_name,
            "procedure_code": proc_code,
            "durations":      durations_list_for_code,
            "optimal":        optimal_for_this_code
        })

    # 6) Posortujmy po kategorii, a potem po kodzie
    history_groups.sort(key=lambda x: (x["category"], x["procedure_code"]))

    # 7) Przygotujmy listę wszystkich kodów do dropdowna (seed + już użyte)
    used = [e.procedure_code for e in history_entries]
    codes = sorted(set(seeded + used))

    # 8) Sprawdźmy, czy mamy GET/POST-owy parametr „procedure_code”
    code = request.args.get("procedure_code") or request.form.get("procedure_code")

    # 9) Jeśli wybrano jakiś code, pobierzmy WSZYSTKIE wcześniejsze czasy dla tego code
    durations_list = []
    if code:
        durations_list = [
            d.duration
            for d in CodeDuration.query.filter_by(
                cabinet_id     = cabinet.id,
                procedure_code = code
            ).all()
        ]
    if request.method == "POST":
        # —————————— 1) Parsowanie kodów i czasów ——————————
        raw_codes = request.form.get("procedure_code", "")
        procedure_codes = [c.strip() for c in raw_codes.split(",") if c.strip()]

        durations_raw = request.form.getlist("new_durations[]")
        durations     = [int(d) for d in durations_raw if d.strip()]

        # —————————— 2) Całkowity czas ——————————
        total_time = sum(durations)

        # —————————— 3) Oblicz liczbę powierzchni dla każdego kodu ——————————
        surface_counts = []
        for pc in procedure_codes:
            parts = pc.split(None, 1)
            surfaces = parts[1] if len(parts) > 1 else ""
            # jeżeli nie ma liter po cyfrze, uznajemy 1 powierzchnię
            sc = len(surfaces) if surfaces else 1
            surface_counts.append(sc)

        # —————————— 4) Wylicz rozkład czasu ——————————
        n_codes = len(procedure_codes)
        # domyślny: równe podzielenie, gdy wszystkie powierzchnie takie same
        if all(sc == surface_counts[0] for sc in surface_counts):
            per_code = total_time // n_codes
            allocs = [per_code] * n_codes
        else:
            total_surfaces = sum(surface_counts)
            allocs = [
                int(round(total_time * sc / total_surfaces))
                for sc in surface_counts
            ]

        # —————————— 5) (Opcjonalnie) debug ——————————
        print("DEBUG codes:", procedure_codes)
        print("DEBUG surfaces:", surface_counts)
        print("DEBUG total_time:", total_time)
        print("DEBUG allocs:", allocs)

        # —————————— 6) Zapis w bazie ——————————
        for pc, allocated in zip(procedure_codes, allocs):
            db.session.add(CodeDuration(
                cabinet_id     = cabinet.id,
                procedure_code = pc,
                duration       = allocated
            ))
        db.session.commit()

        # —————————— 7) Redirect z pierwszym kodem, by widok wiedział, co pokazać ——————————
        first_code = procedure_codes[0] if procedure_codes else None
        return redirect(url_for(
            'add_duration',
            cabinet_id     = cabinet.id,
            treatment_id   = treatment.id,
            procedure_code = first_code
        ))


    # 11) Obliczmy „optymalny” czas dla bieżącego code (jeśli są wartości)
    optimal = "—"
    if durations_list:
        ds = sorted(durations_list)
        n  = len(ds)
        low  = int(n * 0.1)
        high = n - low
        trimmed = ds[low:high] or ds
        optimal = int(sum(trimmed) / len(trimmed))




    # 12) Renderujemy szablon i przekazujemy wszystkie zmienne
    return render_template_string(
        durations_template,
        cabinet        = cabinet,
        treatment      = treatment,
        code           = code,
        durations      = durations_list,
        optimal        = optimal,
        codes          = codes,
        history_groups = history_groups
    )


# ---------------------------
# TRASA DO STATYCZNYCH PLIKÓW (opcjonalnie – dla debugowania obrazu)
# ---------------------------
@app.route("/debug_image")
def debug_image():
    return send_from_directory(app.static_folder, "Lottiimage.png")

# ---------------------------
# URUCHOMIENIE NGROK I APLIKACJI
# ---------------------------
    print("Publiczny URL:", public_url, flush=True)

# —————— Inicjalizacja bazy i seed ——————
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username="admin").first():
        u = User(username="admin")
        u.set_password("password")
        db.session.add(u)
        db.session.commit()

    # ——— Dev-user tylko raz ———

# ——————————————————————————

      # ——— Seed historycznych kodów procedur ———
    hist = [
        ("35 OD", 75),
        ("36 O",  75),
        ("27 OM", 90),
        ("46 O",  45),
        ("36 OD", 60),
        ("46 D",  60),
        ("17 OM", 45),
    ]
    for code, mins in hist:
        if not ProcedureCode.query.get(code):
            pc = ProcedureCode(
                code=code,
                category_name="Mikroskopowe leczenie odtwórcze",
                default_duration=mins
            )
            db.session.add(pc)
    # ————————————————————————————————————————

    # ← TUTAJ WŁOŻYĆ KOD KROKU 1:
    # ——— Seed domyślnych typów zabiegów ———
    default_types = [
        ("Mikroskopowe leczenie odtwórcze",       "Standardowy opis …", 500),
        ("Weryfikacja zębów po leczeniu kanałowym","Standardowy opis …", 500),
        ("Odbudowa protetyczna - nakład",        "Standardowy opis …", 1900),
        ("Odbudowa protetyczna - korona",        "Standardowy opis …", 2000),
        ("Konsultacja implantologiczna celem odbudowy braku zęba",
         "Standardowy opis …",                   250),
        ("Gingiwoplastyka", "Standardowy opis gingiwoplastyki…", 0),
]

    for name, desc, price in default_types:
        if not TreatmentType.query.filter_by(name=name).first():
            tt = TreatmentType(
                name=name,
                default_description=desc,
                default_price=price
            )
            db.session.add(tt)
    # ————————————————————————————————

    db.session.commit()
    # ————————————————————————————————————————————————

    db.session.commit()
    # ————————————————————————————————————————————————

# ————————————————————————————————————————



from flask import jsonify
@app.route("/healthz")
def healthz():
    return jsonify(status="ok")

application = app
