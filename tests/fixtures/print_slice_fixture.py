"""Owned slicer lifecycle fixture, never imported or selected by production configuration."""
import json
from pathlib import Path
import sys
request=json.loads(sys.stdin.buffer.read())
root=Path(request['staging'])
(root/request['output_name']).write_text('; OWNED PROCESS FIXTURE: no real slicing or printer operation\n')
(root/'result.json').write_text(json.dumps({'ok':True}))
