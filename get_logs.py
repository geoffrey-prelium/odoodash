import subprocess
import json
import sys

# Call gcloud with shell=True
result = subprocess.run(
    'gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=odoodash AND severity>=ERROR" --limit=200 --format=json --project=odoodash --freshness=15m',
    shell=True,
    capture_output=True,
    text=True,
    encoding='utf-8'
)

with open('errors.txt', 'w', encoding='utf-8') as f:
    if result.returncode != 0:
        f.write("Error running gcloud: " + result.stderr)
    else:
        logs = json.loads(result.stdout)
        for log in logs:
            f.write(log.get('textPayload', '') + '\n')
