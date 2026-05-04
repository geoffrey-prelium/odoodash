import requests
import os

base_dir = os.path.dirname(os.path.abspath(__file__))
files = ['documentation_utilisateur.md', 'documentation_administrateur.md', 'documentation_developpeur.md']

for f in files:
    file_path = os.path.join(base_dir, f)
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        continue
        
    with open(file_path, 'r', encoding='utf-8') as file:
        md_content = file.read()
    
    data = {'markdown': md_content}
    response = requests.post('https://md-to-pdf.fly.dev', data=data)
    
    if response.status_code == 200:
        pdf_name = f.replace('.md', '.pdf')
        pdf_path = os.path.join(base_dir, pdf_name)
        with open(pdf_path, 'wb') as out:
            out.write(response.content)
        print(f"Generated {pdf_path}")
    else:
        print(f"Error for {f}: {response.status_code} - {response.text}")
