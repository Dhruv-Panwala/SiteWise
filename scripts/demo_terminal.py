"""Readable submission demo. Never reads or writes .env."""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sitewise.webapp import SiteWiseDemo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lat', type=float, default=51.5074)
    parser.add_argument('--lon', type=float, default=-0.1278)
    parser.add_argument('--description', default='Redevelopment of an existing house with a rear extension and two new homes')
    parser.add_argument('--gla', action='store_true', help='Also retrieve GLA spatial layers (slower)')
    parser.add_argument('--prompt-hf-token', action='store_true')
    args = parser.parse_args()
    if args.prompt_hf_token:
        token = getpass.getpass('HF token (hidden; Enter to skip AI): ').strip()
        if token:
            os.environ['HF_TOKEN'] = token
    demo = SiteWiseDemo()
    print('\nSITEWISE UK | Preliminary planning screen', flush=True)
    print(f'Site: {args.lat}, {args.lon}\nProposal: {args.description}', flush=True)
    print('\nReading council guidance and historical applications...', flush=True)
    evidence = demo.analyze({'latitude':args.lat, 'longitude':args.lon,
                             'description':args.description, 'include_gla':args.gla})
    policy = evidence.get('council_policy') or {}
    authority = policy.get('authority') or {}
    print(f"\nCouncil: {authority.get('name') or 'Not verified'} ({authority.get('status', 'unknown')})")
    print('\nCOUNCIL GUIDANCE AND DESIGN CHECKS')
    for item in policy.get('items', []):
        print(f"\n[{item['id']}] {item['title']} ({item['authority']})")
        print('Consider: ' + item['suggested_action'])
        print('Council extract: ' + item['excerpt'])
        print('Document status: ' + item['document_status'])
        print('Source: ' + item['source_url'])
    if not policy.get('items'):
        print('No verified policy text retrieved. No local rules have been assumed.')
    print('\nSPATIAL AND HISTORICAL EVIDENCE')
    matches = [x for x in evidence['planning_constraints'] if x['status'] in {'confirmed', 'historical'}]
    for item in matches:
        print(f"- {item.get('name')}: {item['status']} spatial record; check legal currency.")
    if not matches:
        print('No spatial match retrieved. This does NOT establish that the site is clear.')
    advice = evidence['planning_advice']
    print(f"Nearby applications: {len(evidence['nearby_applications'])}")
    for category in ('comparable_permissions', 'comparable_refusals'):
        cases = advice.get(category, [])
        print(f"{category.replace('_', ' ').capitalize()}: {len(cases)}")
        for case in cases[:3]:
            print(f"  {case.get('application_id')} | {case.get('decision')} | {case.get('description')}")
    print('\nLIMITATIONS')
    for message in policy.get('limitations', []):
        print('- ' + message)
    for error in policy.get('errors', []):
        print('- ' + error['message'])
    print('Tree presence/protection, full plot boundaries and missing constraints must be verified. Similarity is not approval probability.')
    print('\nAI EXPLANATION (may take up to 90 seconds)', flush=True)
    report = demo.explain(evidence['evidence_id'])
    print('Status: ' + report['status'])
    print(report.get('text') or report.get('message') or 'Unavailable; use the sourced guidance above.')
    for citation in report.get('citations', []):
        print(f"[{citation['id']}] {citation.get('source_url') or citation.get('title')}")
    print('\nPreliminary screening, not a planning decision or professional advice.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
