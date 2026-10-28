"""Repository agent discovery, ownership, and delegation contracts."""

import csv
import json
import re
import unittest
from pathlib import Path


class TestAgentContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.agent_dir = cls.root / '.github/agents'
        cls.contract = json.loads((cls.agent_dir / 'ownership.json').read_text(encoding='utf-8'))
        cls.agents = {}
        cls.documents = {}
        for path in cls.agent_dir.glob('*.agent.md'):
            text = path.read_text(encoding='utf-8')
            if not text.startswith('---\n') or len(text.split('---', 2)) != 3:
                raise AssertionError(f'Invalid frontmatter in {path.name}')
            fields = {}
            for line in text.split('---', 2)[1].strip().splitlines():
                key, value = line.split(':', 1)
                fields[key.strip()] = value.strip()
            name = fields['name'].strip('"')
            if name in cls.agents:
                raise AssertionError(f'Duplicate agent name: {name}')
            cls.agents[name] = fields
            cls.documents[name] = text

    def test_reference_roles_are_adapted_and_bo_coordinators_preserved(self):
        self.assertEqual(self.contract['schema_version'], 1)
        self.assertEqual(self.contract['reference_roles']['Tableau'], 'BusinessObjects')
        self.assertEqual(self.contract['reference_roles']['DAX'], 'Dax')
        for source_role, target_role in self.contract['reference_roles'].items():
            with self.subTest(source_role=source_role):
                self.assertIn(target_role, self.agents)
        self.assertTrue({'AgentTools', 'Converter', 'Generator'}.issubset(self.agents))
        self.assertEqual(set(self.contract['owners']), set(self.agents))

    def test_frontmatter_is_discoverable_and_delegations_are_executable(self):
        for name, fields in self.agents.items():
            with self.subTest(agent=name):
                self.assertTrue(fields['name'].startswith('"') and fields['name'].endswith('"'))
                self.assertTrue(fields['description'].startswith('"') and fields['description'].endswith('"'))
                self.assertGreater(len(fields['description']), 30)
                if 'agents' in fields:
                    self.assertIn('agent', fields.get('tools', '').strip('[]').split(', '))
                    self.assertTrue(fields['agents'].startswith('[') and fields['agents'].endswith(']'))
                    targets = next(csv.reader([fields['agents'][1:-1]], skipinitialspace=True))
                    for target in targets:
                        self.assertIn(target, self.agents)
                        self.assertNotEqual(target, name)

    def test_every_engine_module_has_exactly_one_primary_owner(self):
        owners = {}
        for agent, patterns in self.contract['owners'].items():
            for pattern in patterns:
                with self.subTest(agent=agent, pattern=pattern):
                    self.assertNotIn('..', Path(pattern).parts)
                    self.assertFalse(Path(pattern).is_absolute())
                    matches = [path for path in self.root.glob(pattern) if path.is_file()]
                    self.assertTrue(matches, f'Stale ownership pattern: {pattern}')
                    for path in matches:
                        relative = path.relative_to(self.root).as_posix()
                        self.assertNotIn(relative, owners, f'Duplicate owner for {relative}')
                        owners[relative] = agent
        modules = {path.relative_to(self.root).as_posix()
                   for directory in ('bo_export', 'powerbi_import')
                   for path in (self.root / directory).rglob('*.py')}
        self.assertEqual(modules - set(owners), set(), 'Unowned engine modules')

    def test_collaboration_preserves_primary_owner_and_known_roles(self):
        for entry in self.contract['collaboration']:
            with self.subTest(path=entry['path']):
                self.assertTrue((self.root / entry['path']).is_file())
                self.assertIn(entry['path'], self.contract['owners'][entry['primary']])
                self.assertTrue(entry['boundary'].strip())
                for collaborator in entry['collaborators']:
                    self.assertIn(collaborator, self.agents)
                    self.assertNotEqual(collaborator, entry['primary'])

    def test_agent_references_do_not_claim_nonexistent_engine_files(self):
        for name, document in self.documents.items():
            for relative in re.findall(r'`((?:bo_export|powerbi_import)/[\w/.-]+\.py)`', document):
                with self.subTest(agent=name, path=relative):
                    self.assertTrue((self.root / relative).is_file())
        self.assertNotIn('tableau_export/', '\n'.join(self.documents.values()))

    def test_reviewer_is_read_only_and_mcp_owner_is_unambiguous(self):
        self.assertEqual(self.agents['Reviewer']['tools'], '[read, search, todo]')
        self.assertIn('powerbi_import/mcp_server.py', self.contract['owners']['AgentTools'])
        self.assertNotIn('powerbi_import/mcp_server.py', self.contract['owners']['AI'])
        self.assertIn('powerbi_import/migration_quality.py', self.contract['owners']['Evidence'])
        self.assertIn('docs/DEVELOPMENT_PLAN.md', self.contract['owners']['Roadmap Planner'])