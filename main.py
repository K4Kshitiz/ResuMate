
from flask import Flask, request, render_template, redirect, url_for, session, send_file
import openai
import os
from fpdf import FPDF
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "supersecretkey"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///resumate.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# User Model
import re
from datetime import datetime

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Create tables only if they don't exist
with app.app_context():
    db.create_all()

# Set your OpenAI API key from environment variable
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("⚠️ Warning: OPENAI_API_KEY not set in secrets")
client = openai.OpenAI(api_key=api_key)

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    message = ""
    if request.method == "POST":
        try:
            email = request.form.get("email", "").strip()
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            
            # Enhanced validation
            if not all([email, username, password]):
                message = "❌ All fields are required"
            elif not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
                message = "❌ Invalid email format"
            elif len(password) < 8:
                message = "❌ Password must be at least 8 characters"
            elif not re.match(r'^[a-zA-Z0-9_]+$', username):
                message = "❌ Username can only contain letters, numbers and underscore"
            else:
                # Check for existing user atomically
                existing_user = User.query.filter(
                    db.or_(
                        User.email == email,
                        User.username == username
                    )
                ).first()
                
                if existing_user:
                    if existing_user.email == email:
                        message = "❌ Email already registered"
                    else:
                        message = "❌ Username already exists"
                else:
                    new_user = User(username=username, email=email)
                    new_user.set_password(password)
                    db.session.add(new_user)
                    db.session.commit()
                    return redirect(url_for("login"))
        except Exception as e:
            print("Error during signup:", str(e))
            message = "❌ An error occurred during signup"
            db.session.rollback()
            
    return render_template("signup.html", message=message)

@app.route("/login", methods=["GET", "POST"])
def login():
    message = ""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session["user"] = username
            return redirect(url_for("builder"))
        else:
            message = "❌ Invalid credentials"
            
    return render_template("login.html", message=message)

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("home"))

@app.route("/builder", methods=["GET", "POST"])
def builder():
    if "user" not in session:
        return redirect(url_for("login"))

    response = ""
    error = None
    role = experience = skills = ""

    if request.method == "POST":
        role = request.form.get("role", "")
        industry = request.form.get("industry", "")
        education = request.form.get("education", "")
        skills = request.form.get("skills", "")

        companies = request.form.getlist("companies[]")
        job_titles = request.form.getlist("job_titles[]")
        start_dates = request.form.getlist("start_dates[]")
        end_dates = request.form.getlist("end_dates[]")
        achievements = request.form.getlist("achievements[]")

        if not companies or not all(companies):
            error = "Company name required for all experiences"
        elif not all(job_titles):
            error = "Job title required for all experiences"
        elif not all(start_dates):
            error = "Start date required for all experiences"
        elif not all(achievements):
            error = "Achievement required for all experiences"

        if not error:
            work_experience = ""
            for i in range(len(companies)):
                work_experience += f"\nCompany: {companies[i]}\n"
                work_experience += f"Title: {job_titles[i]}\n"
                work_experience += f"Period: {start_dates[i]} to {end_dates[i]}\n"
                work_experience += f"Achievements: {achievements[i]}\n"

            prompt = f"""
            You are a professional resume writer.
            Write resume content for someone applying to a \"{role}\" role in the {industry} industry with {education} education.
            Their skills include:
            {skills}

            Work Experience:
            {work_experience}

            Please include the following:
            - Strong resume headline
            - 3 bullet points under work experience
            - 2 soft skills
            - ATS-optimized, professional tone
            Respond in plain text.
            """

            try:
                if not os.getenv("OPENAI_API_KEY"):
                    print("❌ OpenAI API key missing")
                    return render_template("resume.html", error="OpenAI API key not configured")
                    
                print("🔄 Generating resume...")
                result = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1024,
                    temperature=0.7,
                    timeout=60,  # Increased timeout
                )
                
                if not result or not result.choices:
                    print("❌ Invalid OpenAI response")
                    return render_template("resume.html", error="Failed to generate resume. Please try again.")
                    
                response = result.choices[0].message.content.strip()
                if not response:
                    print("❌ Empty OpenAI response")
                    return render_template("resume.html", error="Generated resume was empty. Please try again.")
                    
                print("✅ Successfully generated resume")
                    
            except openai.AuthenticationError:
                print("🔑 OpenAI API key invalid")
                error = "OpenAI API Error: Invalid API key"
            except openai.RateLimitError:
                print("⏳ OpenAI API rate limit exceeded")
                error = "OpenAI API Error: Rate limit exceeded"
            except Exception as e:
                print("🔥 GPT error:", str(e))
                error = "OpenAI API Error"

    return render_template("resume.html", response=response, error=error)

@app.route("/download", methods=["POST"])
def download_pdf():
    content = request.form.get("pdfcontent", "")
    if not content.strip():
        return "❌ No content to download."
    
    username = session.get('user', 'user')
    filename = f"resume_{username}_{datetime.now().strftime('%Y%m%d')}.pdf"
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.set_text_color(44, 44, 44)
    
    # Add watermark
    pdf.set_font('Arial', 'I', 8)
    pdf.set_text_color(128, 128, 128)
    pdf.text(10, 285, "Generated by Resumate AI")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for line in content.split('\n'):
        pdf.multi_cell(0, 10, line.strip())

    pdf_path = "resume_output.pdf"
    pdf.output(pdf_path)
    return send_file(pdf_path, as_attachment=True, download_name="resume.pdf", mimetype='application/pdf')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
