import requests
from urllib.parse import urljoin

def main(args):

    # Tell the API the current render sttus
    try:
        # get passed-in arguments
        api_url = args['CHOIRLESS_API_URL']
        api_key = args['CHOIRLESS_API_KEY']
        choir_id = args['choir_id']
        song_id = args['song_id']
        part_id = args['part_id']
        status = args['status']

        # pass the apikey in the URL
        params = { 'apikey': api_key }

        # pass everything else in the POST body
        payload = {
                    'choirId': choir_id,
                    'songId': song_id,
                    'partId': part_id,
                    'status': status
                  }

        # make HTTP POST request with application/json header
        requests.post(urljoin(api_url, 'render'), params=params, json=payload)

    except:
        print(f"Could not post render status into the API: choirId {choir_id} songId {song_id} partId {part_id} status {status}")