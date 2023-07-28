import os
import sys
import requests
import datetime
import re
import toml
import logging
import logging.config
from requests.exceptions import HTTPError

from time import sleep

from woocommerce import API
# from woocommerce.exceptions import APIError
from typing import Dict, List

DIR_PATH = os.path.dirname(os.path.realpath(__file__))
PY_ENV = os.getenv('PY_ENV', 'dev')

logging.config.fileConfig('logging.conf')
log = logging.getLogger(PY_ENV)
logger = logging.getLogger()
match PY_ENV:
    case 'dev':
        logger.setLevel(logging.DEBUG)
    case 'prod':
        logger.setLevel(logging.ERROR)

# Read config.toml
def load_config(file_path: str) -> Dict:
    return toml.load(file_path)

config = load_config('config.ini')

api_key = config['westdecor']['api_key']
language = config['westdecor']['language']
page_size = config['westdecor']['page_size']
bearer_token = config['westdecor']['bearer_token']

woocommerce = API(
    url=config['woocommerce']['url'],
    consumer_key=config['woocommerce']['consumer_key'],
    consumer_secret=config['woocommerce']['consumer_secret'],
    wp_api=True,
    version="wc/v3",
    timeout=10
)

# product_fields = {'Id': 0, 'attributes': {}, 'Afbeeldingen': {}}
# new_product_fields = {}

def get_product_data(api_key: str, language: str, page_size: int, page_num: int, bearer_token: str)->List[Dict]:
    url = "https://www.westdecor.be/rest/V1/webservice/products/"
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "api_key": api_key,
        "language": language,
        "page_size": page_size,
        "page_num": page_num,
        "show_all_attributes": True
    }
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

def process_product_data(data:dict={},product_fields:dict={})->dict:
    new_fields = {}
    for idx, product in enumerate(data['products']):
        new_fields =  product_fields | product

    return new_fields

def processed_output(page_num:int = 0, total_products_processed:int = 0)->str:
    message = "\n"
    message += f"Page number: {page_num}\n"
    message += f"Total products processed: {total_products_processed}\n"
    logging.info(message)

def main():
    global page_num
    page_num = 1
    test_run = True
    update_hours_threshold = 24  # Set the desired threshold for updating products in hours
    products_with_missing_parents = []  # Used to store products with missing parents
    total_products_processed = 0    # Used to keep track of the total number of products processed
    delay_seconds = 1  # Set the desired delay between requests in seconds

    if len(sys.argv) > 1:
        page_num = int(sys.argv[1])
        if page_num <= 0:
            page_num = 1
        try:
            test_run = bool(int(sys.argv[2]))
        except Exception as e:
            logging.error(e)
            test_run = True
    else:
         # Ask for the starting page_num using input()
        page_num = int(input("Enter the starting page number: "))

    product_fields = {}
    while True:
        data = {}
        if not (data := get_product_data(api_key, language, page_size, page_num, bearer_token)):
            break

        if (product_fields := process_product_data(data=data, product_fields=product_fields)):
            print(product_fields)
            processed_output(page_num= page_num,
                            total_products_processed=total_products_processed)
            page_num += 1
            continue

        page_num += 1

if __name__ == '__main__':
    main()
