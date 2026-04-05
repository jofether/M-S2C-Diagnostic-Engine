#!/usr/bin/env python3
import urllib.request
import urllib.parse
import json

# Test the same query as the screenshot
bug_description = "[components/UserTestimonials.jsx] - Testimonial cards extend far beyond the visible screen boundary to the right, with multiple reviews completely cut off and inaccessible because horizontal scrolling is disabled and hidden"

data = urllib.parse.urlencode({'bug_description': bug_description}).encode('utf-8')
req = urllib.request.Request('http://localhost:8000/api/diagnose', data=data, method='POST')

print("Testing backend /api/diagnose endpoint...")
print(f"Query: {bug_description[:80]}...")
print()

response = urllib.request.urlopen(req)
result = json.loads(response.read().decode('utf-8'))

print(f"Status: {result.get('status')}")
print(f"Indexed: {result.get('indexed')}")
print(f"Using real data: {result.get('using_real_data')}")
print(f"Candidates returned: {len(result.get('candidates', []))}")
print()

if result.get('candidates'):
    print("FIRST 3 CANDIDATES:")
    for i, cand in enumerate(result.get('candidates', [])[:3]):
        print(f"  {i+1}. {cand.get('file')} (L:{cand.get('lines')}) - Score: {cand.get('confidence')}")
else:
    print("⚠️  NO CANDIDATES RETURNED!")
    print(f"Response: {json.dumps(result, indent=2)}")
