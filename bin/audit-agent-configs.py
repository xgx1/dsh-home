
import os, re, json, yaml, fnmatch
names = []
for d in sorted(os.listdir('/home/sx/.dsh/skills')):
    skill = os.path.join('/home/sx/.dsh/skills', d, 'SKILL.md')
    if not os.path.exists(skill): continue
    name = d
    try:
        txt = open(skill, encoding='utf-8').read()[:2000]
        m = re.search(r'^name:\s*(.+)$', txt, re.M)
        if m: name = m.group(1).strip().strip('"\'')
    except Exception: pass
    names.append(name)
names = sorted(set(names))
doc = yaml.safe_load(open('/home/sx/.dsh/agent-configs.yaml', encoding='utf-8'))
patterns = []
for body in doc['configs'].values():
    patterns += body.get('skills') or []
def covered(n): return any(fnmatch.fnmatchcase(n, p) for p in patterns)
unc = [n for n in names if not covered(n)]
print('total', len(names), 'covered', len(names)-len(unc), 'uncovered', len(unc))
print('\n'.join(unc))
