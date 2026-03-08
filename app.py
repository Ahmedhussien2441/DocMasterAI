import os
import glob
import io
import datetime
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory, url_for, redirect
from werkzeug.utils import secure_filename

# File Conversion
from pdf2docx import Converter
from docx import Document
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

# PDF Tools
from PyPDF2 import PdfReader, PdfWriter

# OCR
import pytesseract
import fitz  # PyMuPDF
from PIL import Image

# AI Text Organizer (Gemini)
import google.generativeai as genai

app = Flask(__name__)
# Secret key for session, not strictly necessary if not using flash
app.secret_key = 'super_secret_docmaster_key'

# Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
CONVERTED_FOLDER = os.path.join(BASE_DIR, 'converted')
OCR_FOLDER = os.path.join(BASE_DIR, 'ocr')
EXPORTS_FOLDER = os.path.join(BASE_DIR, 'exports')

for folder in [UPLOAD_FOLDER, CONVERTED_FOLDER, OCR_FOLDER, EXPORTS_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# Google AI Studio configurations
GEMINI_API_KEY = "AIzaSyAJzXp_MrlXDBNDtDDjahBItWqneZ6fyWY"
genai.configure(api_key=GEMINI_API_KEY)

# Ensure Tesseract path is set correctly if running on windows/linux.
# For local Windows, it usually requires setting pytesseract.pytesseract.tesseract_cmd
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'docx'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_unique_filename(filename):
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{timestamp}_{filename}"

# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/manifest.json')
def manifest():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'manifest.json', mimetype='application/manifest+json')

@app.route('/service-worker.js')
def service_worker():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'service-worker.js', mimetype='application/javascript')

@app.route('/favicon.ico')
def favicon():
    # Return empty 204 to prevent 404 errors in browser logs
    return '', 204

# 1. FILE CONVERSION
@app.route('/convert', methods=['POST'])
def convert_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    target_format = request.form.get('target', 'pdf')
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        safe_filename = generate_unique_filename(filename)
        filepath = os.path.join(UPLOAD_FOLDER, safe_filename)
        file.save(filepath)
        
        ext = filename.rsplit('.', 1)[1].lower()
        output_filename = f"{safe_filename.rsplit('.', 1)[0]}.{target_format}"
        output_filepath = os.path.join(CONVERTED_FOLDER, output_filename)
        
        try:
            if ext == 'pdf' and target_format == 'docx':
                cv = Converter(filepath)
                cv.convert(output_filepath)
                cv.close()
            elif ext == 'docx' and target_format == 'pdf':
                # Simplified docx to pdf (basic conversion via ReportLab for free usage, 
                # or better using COM/unoconv if available. We will do a simple text extract 
                # to ReportLab for lightweight, though formatting may drop)
                doc = Document(filepath)
                c = canvas.Canvas(output_filepath, pagesize=letter)
                y = 750
                for para in doc.paragraphs:
                    if y < 50:
                        c.showPage()
                        y = 750
                    c.drawString(50, y, para.text[:100]) # truncated for basic layout
                    y -= 20
                c.save()
            elif ext in ['jpg', 'jpeg', 'png'] and target_format == 'pdf':
                image = Image.open(filepath)
                pdf_bytes = image.convert('RGB')
                pdf_bytes.save(output_filepath)
            elif ext == 'txt' and target_format == 'pdf':
                c = canvas.Canvas(output_filepath, pagesize=letter)
                with open(filepath, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                y = 750
                for line in lines:
                    if y < 50:
                        c.showPage()
                        y = 750
                    c.drawString(50, y, line.strip())
                    y -= 20
                c.save()
            else:
                return jsonify({'error': 'Conversion not supported'}), 400
            
            return jsonify({'success': True, 'filename': output_filename, 'url': f'/download/converted/{output_filename}'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

# 1.5. PDF TO WORD CONVERTER
@app.route('/pdf_to_word', methods=['POST'])
def pdf_to_word():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and file.filename.endswith('.pdf'):
        filename = secure_filename(file.filename)
        safe_filename = generate_unique_filename(filename)
        filepath = os.path.join(UPLOAD_FOLDER, safe_filename)
        file.save(filepath)
        
        output_filename = f"{safe_filename.rsplit('.', 1)[0]}.docx"
        output_filepath = os.path.join(CONVERTED_FOLDER, output_filename)
        
        try:
            cv = Converter(filepath)
            cv.convert(output_filepath)
            cv.close()
            return jsonify({'success': True, 'filename': output_filename, 'url': f'/download/converted/{output_filename}'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    return jsonify({'error': 'Invalid file format. Must be PDF'}), 400

# 2. PDF TOOLS
@app.route('/pdf-tools/merge', methods=['POST'])
def merge_pdfs():
    files = request.files.getlist('files')
    if not files or len(files) < 2:
        return jsonify({'error': 'Need at least two PDF files to merge'}), 400
    
    merger = PdfWriter()
    for file in files:
        if file.filename.endswith('.pdf'):
            reader = PdfReader(file)
            for page in reader.pages:
                merger.add_page(page)
                
    output_filename = generate_unique_filename('merged.pdf')
    output_filepath = os.path.join(CONVERTED_FOLDER, output_filename)
    
    with open(output_filepath, 'wb') as f:
        merger.write(f)
        
    return jsonify({'success': True, 'filename': output_filename, 'url': f'/download/converted/{output_filename}'})

@app.route('/pdf-tools/split', methods=['POST'])
def split_pdf():
    file = request.files['file']
    range_str = request.form.get('range', '') # e.g. "1-3"
    
    if not file or not file.filename.endswith('.pdf'):
        return jsonify({'error': 'Invalid PDF file'}), 400
        
    try:
        start_page, end_page = map(int, range_str.split('-'))
        # 1-indexed to 0-indexed
        start_page -= 1
        
        reader = PdfReader(file)
        writer = PdfWriter()
        
        for i in range(start_page, min(end_page, len(reader.pages))):
            writer.add_page(reader.pages[i])
            
        output_filename = generate_unique_filename('split.pdf')
        output_filepath = os.path.join(CONVERTED_FOLDER, output_filename)
        
        with open(output_filepath, 'wb') as f:
            writer.write(f)
            
        return jsonify({'success': True, 'filename': output_filename, 'url': f'/download/converted/{output_filename}'})
    except Exception as e:
        return jsonify({'error': f"Invalid range or Error: {str(e)}"}), 400

# 3. OCR SCANNER
@app.route('/ocr', methods=['POST'])
def ocr_process():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    lang = request.form.get('lang', 'eng') # eng or ara
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    filename = secure_filename(file.filename)
    safe_filename = generate_unique_filename(filename)
    filepath = os.path.join(OCR_FOLDER, safe_filename)
    file.save(filepath)
    
    ext = filename.rsplit('.', 1)[1].lower()
    text = ""
    
    try:
        if ext in ['jpg', 'jpeg', 'png']:
            img = Image.open(filepath)
            # tesseract needs "ara" for arabic, "eng" for english. Or "eng+ara"
            tesseract_lang = 'eng+ara' if lang == 'ara' else 'eng'
            text = pytesseract.image_to_string(img, lang=tesseract_lang)
        elif ext == 'pdf':
            doc = fitz.open(filepath)
            tesseract_lang = 'eng+ara' if lang == 'ara' else 'eng'
            for page in doc:
                # Get a high resolution pixmap for OCR
                pix = page.get_pixmap(dpi=200)
                mode = "RGBA" if pix.alpha else "RGB"
                img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                text += pytesseract.image_to_string(img, lang=tesseract_lang) + "\n"
                
        return jsonify({'success': True, 'text': text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 4. AI TEXT ORGANIZER (Gemini API)
@app.route('/ai-text', methods=['POST'])
def ai_text_process():
    data = request.json
    text = data.get('text', '')
    action = data.get('action', 'summarize')
    
    if not text:
        return jsonify({'error': 'No text provided'}), 400
        
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompts = {
            'clean': f"Fix OCR errors and spelling in the following text:\n\n{text}",
            'grammar': f"Fix grammar and improve readability of the following text:\n\n{text}",
            'restructure': f"Restructure the following text to make it flow better:\n\n{text}",
            'bullets': f"Convert the following text into concise bullet points:\n\n{text}",
            'summarize': f"Provide a brief summary of the following text:\n\n{text}",
            'highlight': f"Extract and highlight the key ideas from the following text:\n\n{text}"
        }
        
        prompt = prompts.get(action, prompts['summarize'])
        response = model.generate_content(prompt)
        
        return jsonify({'success': True, 'result': response.text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 5. DOCUMENT MANAGER
@app.route('/documents', methods=['GET'])
def list_documents():
    files = []
    
    def process_folder(folder, category):
        if os.path.exists(folder):
            for f in os.listdir(folder):
                if os.path.isfile(os.path.join(folder, f)):
                    files.append({
                        'name': f,
                        'category': category,
                        'url': f'/download/{category}/{f}',
                        'delete_url': f'/delete/{category}/{f}',
                        'size': os.path.getsize(os.path.join(folder, f))
                    })
                    
    process_folder(UPLOAD_FOLDER, 'uploads')
    process_folder(CONVERTED_FOLDER, 'converted')
    process_folder(OCR_FOLDER, 'ocr')
    process_folder(EXPORTS_FOLDER, 'exports')
    
    return jsonify({'documents': files})

@app.route('/download/<category>/<filename>', methods=['GET'])
def download_file(category, filename):
    folders = {
        'uploads': UPLOAD_FOLDER,
        'converted': CONVERTED_FOLDER,
        'ocr': OCR_FOLDER,
        'exports': EXPORTS_FOLDER
    }
    if category in folders:
        return send_from_directory(folders[category], filename, as_attachment=True)
    return "Not found", 404

@app.route('/delete/<category>/<filename>', methods=['DELETE'])
def delete_file(category, filename):
    folders = {
        'uploads': UPLOAD_FOLDER,
        'converted': CONVERTED_FOLDER,
        'ocr': OCR_FOLDER,
        'exports': EXPORTS_FOLDER
    }
    if category in folders:
        filepath = os.path.join(folders[category], secure_filename(filename))
        if os.path.exists(filepath):
            os.remove(filepath)
            return jsonify({'success': True})
    return jsonify({'error': 'File not found'}), 404

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
