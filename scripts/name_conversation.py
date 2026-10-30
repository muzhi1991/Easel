"""Invoke the current turn's naming capability supplied by Easel Web."""
import argparse
import json
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--token', required=True)
    parser.add_argument('--mode', choices=['manual', 'artifact'], required=True)
    parser.add_argument('--title', required=True)
    args = parser.parse_args()
    request = urllib.request.Request(args.url, data=json.dumps(
        {'title': args.title, 'mode': args.mode}, ensure_ascii=False).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + args.token})
    # Local callback must not use inherited proxies.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request) as response:
        print(response.read().decode())


if __name__ == '__main__':
    main()
