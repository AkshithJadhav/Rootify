from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
import os
from werkzeug.utils import secure_filename
import re
import requests
from dotenv import load_dotenv
import os
app = Flask(__name__)
load_dotenv()

# Replace with your Trefle API Key
TREFLE_API_KEY = os.getenv('TREFLE_API')
BASE_URL = 'https://trefle.io/api/v1/'


# Configure upload folder
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Configure Gemini API
genai.configure(api_key=os.getenv('GEMINI_API'))
generation_config = {
    "temperature": 0.9,
    "top_p": 1,
    "top_k": 1,
    "max_output_tokens": 2048
}
model = genai.GenerativeModel("gemini-1.5-flash", generation_config=generation_config)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def format_analysis(text):
    # Remove markdown formatting if present
    text = re.sub(r'[*_#]', '', text)
    
    # Initialize dictionary to store sections
    sections = {}
    current_section = None
    current_content = []
    
    # Split text into lines and process
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check for section headers (various formats)
        header_match = re.match(r'^(?:\d+\.?\s*)?([^:]+)[:|-](.*)$', line)
        
        if header_match or line.isupper():  # Consider all-caps lines as headers too
            # Save previous section if exists
            if current_section and current_content:
                sections[current_section] = ' '.join(current_content).strip()
            
            # Start new section
            if header_match:
                current_section = header_match.group(1).strip()
                initial_content = header_match.group(2).strip()
                current_content = [initial_content] if initial_content else []
            else:
                current_section = line
                current_content = []
        else:
            if current_section:  # Add to current section if one exists
                current_content.append(line)
            else:  # Create a default section if no section exists
                current_section = "General Information"
                current_content.append(line)
    
    # Add the last section
    if current_section and current_content:
        sections[current_section] = ' '.join(current_content).strip()
    
    # Convert sections to the expected format
    formatted_data = {}
    for key, value in sections.items():
        formatted_data[key] = value
    
    return formatted_data

@app.route('/')
def index():
    return render_template('home.html')

@app.route('/index')
def upload_page():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        
        if file and allowed_file(file.filename):
            # Read the file content before saving
            file_content = file.read()
            
            # Reset file pointer to beginning
            file.seek(0)
            
            # Save the file
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # Process with Gemini API
            image_part = {
                "mime_type": file.content_type,
                "data": file_content
            }
            
            prompt_parts = [
                """Analyze this image and provide detailed information about the plant with the following aspects. For each heading, provide specific, detailed information based on what you observe in the image:

                1. Scientific Name: Provide the botanical name
                2. Family: State the plant family
                3. Common Names: List common or local names
                4. Type: Specify plant type (tree, shrub, herb, etc.)
                5. Size: Detail typical height and spread
                6. Leaf Shape: Describe leaf morphology
                7. Leaf Texture: Describe leaf surface and feel
                8. Flowers/Fruit: Describe flowering characteristics and fruits
                9. Native Habitat: List original geographic regions
                10. Climate: Describe preferred climate conditions
                11. Soil Preference: Detail soil requirements
                12. Care Instructions: Provide light, water, and fertilizer needs
                13. Maintenance: List pruning and general maintenance needs
                14. Interesting Facts: Share unique characteristics or historical facts
                15. Uses: Detail ornamental, practical, or cultural uses

                For each aspect, provide the heading followed by a colon and then the detailed information.""",
                image_part
            ]
            
            response = model.generate_content(prompt_parts)
            analysis_data = format_analysis(response.text)
            
            return jsonify({
                'success': True,
                'display_data': analysis_data,
                'image_path': f'/static/uploads/{filename}'
            })
            
        return jsonify({'error': 'Invalid file type'}), 400

    except Exception as e:
        print("Error:", str(e))
        return jsonify({'error': str(e)}), 500
    

@app.route('/species')
def species():
    """Load categories on the homepage."""
    try:
        # Fetch plant categories or families from the Trefle API
        response = requests.get(
            f"{BASE_URL}/plants",
            params={'token': TREFLE_API_KEY}
        )
        response.raise_for_status()
        data = response.json()
        categories = set(plant['family'] for plant in data['data'] if plant['family'])  # Extract unique families
        return render_template('species.html', categories=sorted(categories))
    except Exception as e:
        return render_template('species.html', error="Error fetching categories.", categories=[])

@app.route('/category/<category>')
def get_plants_by_category(category):
    try:
        page = request.args.get('page', 1, type=int)
        response = requests.get(
            'https://trefle.io/api/v1/species',
            params={
                'token': TREFLE_API_KEY,
                'filter[family_name]': category,
                'page': page,
                'per_page': 20
            }
        )
        
        if response.status_code != 200:
            return jsonify({'error': f'API Error: {response.status_code}'}), 400
            
        data = response.json()
        plants = data.get('data', [])
        
        return jsonify({'plants': plants})
    except Exception as e:
        print(f"Exception: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
@app.route('/map')
def map_page():
    return render_template('map.html')


@app.route('/chat')
def chat():
    return render_template('chat.html')

@app.route('/chat_response', methods=['POST'])
def chat_response():
    try:
        user_input = request.json.get('message')
        chat = model.start_chat(history=[])
        response = chat.send_message(f"Answer this plant-related question: {user_input}. Only answer if the question is related to plants, gardening, or botany. Otherwise, respond that you can only answer plant-related questions.")
        return jsonify({'response': response.text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    
@app.route('/get_plant_details', methods=['POST'])
def get_plant_details():
    try:
        data = request.json
        plant_name = data.get('plant_name')
        
        if not plant_name:
            return jsonify({'error': 'Plant name is required'}), 400

        # Create the prompt for Gemini
        prompt = f"""Provide detailed information about the plant {plant_name} with the following aspects:

        1. Scientific Name: Provide the botanical name
        2. Family: State the plant family
        3. Common Names: List common or local names
        4. Type: Specify plant type (tree, shrub, herb, etc.)
        5. Size: Detail typical height and spread
        6. Leaf Characteristics: Describe leaf morphology and texture
        7. Flowers/Fruit: Describe flowering characteristics and fruits
        8. Native Habitat: List original geographic regions
        9. Climate: Describe preferred climate conditions
        10. Growing Requirements: Detail soil, light, and water needs
        11. Uses: Detail ornamental, practical, or cultural uses
        12. Interesting Facts: Share unique characteristics or historical facts

        For each aspect, provide detailed information."""

        # Get response from Gemini
        chat = model.start_chat(history=[])
        response = chat.send_message(prompt)
        
        # Format the response
        analysis_data = format_analysis(response.text)
        
        return jsonify({
            'success': True,
            'details': analysis_data
        })

    except Exception as e:
        print(f"Error in get_plant_details: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug="true")