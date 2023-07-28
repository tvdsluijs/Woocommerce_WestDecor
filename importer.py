import os
import sys
import requests
import datetime
import re
import toml
import logging
import logging.config
from requests.exceptions import HTTPError, ReadTimeout, ConnectionError

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

categorien = config["categorien"]

def check_cats(categories:list = [], subcategories:list = [], sku:str="" )->bool:
    # no categories in Westdecor, then skip
    if not categories:
        logging.info(f"No WestDecor categories? {categories} at {sku}")
        return False

    #flatten Westdecor categories
    WestDecorCats = [category['name'].lower() for category in categories]

    WestDecorSubCats = []
    if subcategories:
        #flatten Westdecor sub categories
        WestDecorSubCats = [category['name'].lower() for category in subcategories]

    for key, value in categorien.items():
        # not in Main category ,then False
        if key.lower() not in WestDecorCats:
            continue

        # If empty WestDecor SubCats return True
        if not WestDecorSubCats:
            logging.info(f"No WestDecor westcategories? {WestDecorSubCats} at {sku}")
            return True

        # If config subcats are empty return True
        try:
            if not value['sub_cats']:
                return True
        except KeyError:
            return True

        # if config subcats not empty check if in WestDecorSubCats
        for subcat in value['sub_cats']:
            if subcat.lower() in WestDecorSubCats:
                return True

        logging.info(f"No config westcategories? {value['sub_cats']}, in WestDecor cats {WestDecorSubCats}")
    # not jumped out yet? Then False
    return False

def get_product_data(api_key: str, language: str, page_size: int, page_num: int, bearer_token: str) -> dict:
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

def process_product_data(data:dict = {})->list:
    indices_to_remove = []

    # for item in data['products']:
    for idx, product in enumerate(data['products']):
        #check if product in category or subcategory
        if product['is_part_of_variant'] != 'Yes':
            if not check_cats(categories=product['attributes']["categories"], subcategories=product['attributes']["subcategories"], sku=product['Sku'] ):
                indices_to_remove.append(idx)
                continue

        data['products'][idx]['Aankoopprijs'] = product['Aankoopprijs'].replace('€ ', '').replace(" ", "")
        data['products'][idx]['Verkoopprijs'] = product['Verkoopprijs'].replace('€ ', '').replace(" ", "")

    #remove products not needed in import
    data['products'] = [item for index, item in enumerate(data['products']) if index not in indices_to_remove]

    return data['products']

def perform_request_with_retries(request_function, *args, **kwargs):
    retries = 5
    delay_seconds = 20

    for attempt in range(retries):
        try:
            response = request_function(*args, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 443 and attempt < retries - 1:
                sleep(delay_seconds)
                continue
            raise

def perform_posts_with_retries(request_function, *args, **kwargs):
    retries = 5
    delay_seconds = 20

    for attempt in range(retries):
        try:
            return request_function(*args, **kwargs)
        except (ConnectionError, ReadTimeout) as e:
            print(e)
            sleep(delay_seconds)
            # continue
        except HTTPError as e:
            response = e.response
            if response.status_code == 443 and attempt < retries - 1:  # Adjust the status_code based on your need
                sleep(delay_seconds)
                continue
            raise


def get_width_height(string:str)->dict:
    pattern = r'(\d+)x(\d+)cm'
    match = re.search(pattern, string)
    if match:
        try:
            return {'width':f"{match.group(1)}" , 'height':f"match.group(2)", 'lenght': ""}
        except (Exception, KeyError):
            return {}
    else:
        return {}

def get_height_radius(string:str)->dict:
    if 'Ø' in string:
        try:
            pattern = r'[0-9]+,[0-9]+|[0-9]+'
            numbers = re.findall(pattern, string)
            return {'width':f"{numbers[1]}", 'height':f"{numbers[1]}", 'lenght': ""}
        except (Exception, KeyError):
            return {}
    else:
        return {}

def update_or_create_product(product: Dict, products_with_missing_parents: List[Dict], update_hours_threshold: int, test_run:bool=False):
    sku = product['Sku']
    existing_product = False
    parent_product = False
    if not test_run:
        if (woo_data := perform_request_with_retries(woocommerce.get, f"products?sku={sku}")):
            existing_product = woo_data.json()

    try:
        gewicht = product['attributes']['weight']
    except (Exception, KeyError):
        gewicht = ""

    try:
        if (afmetingen := get_width_height(product['attributes']['afmetingen'])):
            pass
        elif(afmetingen := get_height_radius(product['attributes']['afmetingen'])):
            pass
        else:
            afmetingen = {'width':"",'height':"",'lenght':""}
    except (Exception, KeyError):
        afmetingen = {'width':"",'height':"",'lenght':""}

    if not existing_product:

        product_data = {
            'sku': sku,
            'name': product['Naam'],
            'regular_price': product['Verkoopprijs'],
            'description': product['Omschrijving'] if product['Omschrijving'] else product['Korte omschrijving'],
            'short_description': product['Korte omschrijving'],
            'images': [
                {
                    'src': product['Afbeeldingen']['Hoofd'],
                    'name': product['Naam'],
                    'alt': product['Naam']
                }
            ],
            'stock_quantity': product['Hoeveelheid in stock']
        }

        if gewicht and gewicht != '0.000000' or float(gewicht) > 0:
            product_data['weight'] = gewicht

        if afmetingen['lenght'] or afmetingen['width'] or afmetingen['height']:
            product_data["dimensions"] = {
                                            "length": afmetingen['lenght'],
                                            "width": afmetingen['width'],
                                            "height": afmetingen['height']
                                        }

        if not product['variant_parent']:
            product_data['type'] = 'variable' if product['has_variants'] == 'Yes' else 'simple'

    else:
        product_data = {
            'sku': sku,
            'regular_price': product['Verkoopprijs'],
            'stock_quantity': product['Hoeveelheid in stock']
        }

    if product['Verkoopprijs'] == "0,00" or float(product['Verkoopprijs'].replace(',', '.')) <= 0:
        product_data['catalog_visibility'] = 'hidden'

    if test_run:
        if product['is_part_of_variant'] == 'Yes':
            logging.info(f"WestDecor product is part of variant, {product['is_part_of_variant']}")

        if product['has_variants'] == 'Yes' and not product['variant_children'] :
            logging.info(f"WestDecor product has variants but no  variant_children! Main SKU: {product['Sku']}")

        if product['has_variants'] == 'No' and product['variant_children']:
            logging.info(f"WestDecor product has no variants but it has variant_children {product['variant_children']}! Main SKU: {product['Sku']}")

        if product['is_part_of_variant'] == 'Yes' and not product['variant_parent']:
            logging.info(f"WestDecor product variant but it has no variant_parent? Main SKU {product['Sku']}")

        if product['is_part_of_variant'] == 'No' and product['variant_parent']:
            logging.info(f"WestDecor product is no variant but it has variant_parent {product['variant_parent']}? Main SKU {product['Sku']}")

    # Product is part van variant and parent not empty
    if product['is_part_of_variant'] == 'Yes' and product['variant_parent']:
        logging.info(f"Product variant parent {product['variant_parent']} Main SKU {product['Sku']}")

        #get Parent Product
        if (woo_data := perform_request_with_retries(woocommerce.get, f"products?sku={product['variant_parent']}")):
            parent_product = woo_data.json()

        product['image'] = { "src":product['Afbeeldingen']['Hoofd'], 'name': product['Naam'],'alt': product['Naam'] }

        # product['attributes'] = [
        #         {
        #         "id": 6,
        #         "option": product['attributes']['color']
        #         }
        # ]

        # del product['images']

        # If parent not found, add the product to the list of products with missing parents
        if not parent_product:
            products_with_missing_parents.append(product)
            return

    #if test run, no need for update insert statements below
    if test_run:
        return

    # not an existing product but a product variation, insert
    if not existing_product and parent_product:
        try:
            # perform_posts_with_retries(woocommerce.post, f"products/{parent_product[0]['id']}/variations", product_data)
            r = woocommerce.post(f"products/{parent_product[0]['id']}/variations", product_data)

# https://github.com/woocommerce/woocommerce-rest-api-docs/blob/trunk/source/includes/wp-api-v3/_product-categories.md
# https://github.com/woocommerce/woocommerce-rest-api-docs/blob/trunk/source/includes/wp-api-v3/_product-attributes.md
# https://github.com/woocommerce/woocommerce-rest-api-docs/blob/trunk/source/includes/wp-api-v3/_product-variations.md

# Attribuut aanmaken
# const data = {
#   name: "Color",
#   slug: "pa_color",
#   type: "select",
#   order_by: "menu_order",
#   has_archives: true
# };

            return
        except HTTPError as e:
            logging.error(f'Request failed after several attempts: {e}')

    # not an existing product and no product variation, insert
    if not existing_product and not parent_product:
        try:
            perform_posts_with_retries(woocommerce.post, 'products', product_data)
            return
        except HTTPError as e:
            logging.error(f'Request failed after several attempts: {e}')

    # if existing product (single/variation or part of variation), update
    if existing_product:
        product_id = existing_product[0]['id']
        last_modified_time = datetime.datetime.fromisoformat(existing_product[0]['date_modified'])
        time_since_last_update = datetime.datetime.utcnow() - last_modified_time

        if time_since_last_update >= datetime.timedelta(hours=update_hours_threshold):
            # woocommerce.put(f'products/{product_id}', product_data)
            try:
                perform_posts_with_retries(woocommerce.put, f'products/{product_id}', product_data)
                return
            except HTTPError as e:
                logging.error(f'Request failed after several attempts: {e}')


def processed_output(page_num:int = 0, total_products_processed:int = 0, products_with_missing_parents:list = []):
    message = "\n"
    message += f"Page number: {page_num}\n"
    message += f"Total products processed: {total_products_processed}\n"
    message += f"Total products with missing parents: {len(products_with_missing_parents)}\n"
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
        test_run = int(input("Is this a test? [0=False, 1=True]: "))

    data = {}
    while True:
        data = get_product_data(api_key, language, page_size, page_num, bearer_token)

        # if empty stop script
        if not data:
            break

        if not (products := process_product_data(data=data)):
            processed_output(page_num= page_num,
                            total_products_processed=total_products_processed,
                            products_with_missing_parents=products_with_missing_parents)
            page_num += 1
            continue

        for product in products:
            update_or_create_product(product=product, products_with_missing_parents=products_with_missing_parents, update_hours_threshold=update_hours_threshold, test_run=test_run)
            if not test_run:
                sleep(delay_seconds)  # Add a delay between requests

            total_products_processed += 1

        processed_output(page_num= page_num,
                        total_products_processed=total_products_processed,
                        products_with_missing_parents=products_with_missing_parents)

        page_num += 1

    # Try to process products with missing parents again
    for product in products_with_missing_parents:
        update_or_create_product(product=product, products_with_missing_parents=[], update_hours_threshold=update_hours_threshold, test_run=test_run)
        if not test_run:
            sleep(delay_seconds)  # Add a delay between requests

        processed_output(page_num= page_num,
                        total_products_processed=total_products_processed,
                        products_with_missing_parents=products_with_missing_parents)


if __name__ == '__main__':
    main()
