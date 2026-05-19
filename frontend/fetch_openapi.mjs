import fs from 'fs';
fetch('https://pw.pioneer.fan:84/api/v1/openapi.json').then(r=>r.json()).then(j=>fs.writeFileSync('openapi.json', JSON.stringify(j, null, 2)));
