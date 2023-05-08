import requests
from woocommerce import API
from typing import Dict, List
from time import sleep
import datetime
import toml

# Read config.toml
config_toml = toml.load('config.ini')

api_key = config_toml['westdecor']['api_key']
language = config_toml['westdecor']['language']
page_size = config_toml['westdecor']['page_size']
bearer_token = config_toml['westdecor']['bearer_token']

page_num = 1

woocommerce = API(
    url=config_toml['woocommerce']['url'],
    consumer_key=config_toml['woocommerce']['consumer_key'],
    consumer_secret=config_toml['woocommerce']['consumer_secret'],
    wp_api=True,
    version="wc/v3",
    timeout=10
)

def get_product_data(api_key: str, language: str, page_size: int, page_num: int, bearer_token: str) -> List[Dict]:
    url = "https://www.westdecor.be/rest/V1/webservice/products/"
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "api_key": api_key,
        "language": language,
        "page_size": page_size,
        "page_num": page_num
    }
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()

    for item in data:
        item['Aankoopprijs'] = item['Aankoopprijs'].replace('€ ', '')
        item['Verkoopprijs'] = item['Verkoopprijs'].replace('€ ', '')

    return data

def perform_request_with_retries(request_function, *args, **kwargs):
    retries = 3
    delay_seconds = 10

    for attempt in range(retries):
        try:
            response = request_function(*args, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 443 and attempt < retries - 1:
                time.sleep(delay_seconds)
                continue
            raise

def update_or_create_product(product: Dict, products_with_missing_parents: List[Dict], update_hours_threshold: int):
    sku = product['Sku']
    existing_product = perform_request_with_retries(woocommerce.get, f"products?sku={sku}").json()

    product_type = 'variable' if product['has_variants'] == 'Yes' else 'simple'

    product_data = {
        'sku': sku,
        'name': product['Naam'],
        'regular_price': product['Verkoopprijs'],
        'description': product['Omschrijving'] if product['Omschrijving'] else '',
        'short_description': product['Korte omschrijving'],
        'images': [
            {
                'src': product['Afbeeldingen']['Hoofd'],
                'name': product['Naam']
            }
        ],
        'stock_quantity': product['Hoeveelheid in stock'],
        'type': product_type
    }

    if product['is_part_of_variant'] == 'Yes':
        parent_sku = product['variant_parent']
        parent_product = perform_request_with_retries(woocommerce.get, f"products?sku={parent_sku}").json()

        if parent_product:
            product_data['parent_id'] = parent_product[0]['id']
        else:
            # If parent not found, add the product to the list of products with missing parents
            products_with_missing_parents.append(product)
            return

    if not existing_product:
        # Create a new product
        woocommerce.post('products', product_data)
    else:
        # Update existing product
        product_id = existing_product[0]['id']
        last_modified_time = datetime.datetime.fromisoformat(existing_product[0]['date_modified'])
        time_since_last_update = datetime.datetime.utcnow() - last_modified_time

        if time_since_last_update >= datetime.timedelta(hours=update_hours_threshold):
            woocommerce.put(f'products/{product_id}', product_data)

def main():
    global page_num
    update_hours_threshold = 24  # Set the desired threshold for updating products in hours
    previous_first_item = None # Used to check if the last page has been reached
    products_with_missing_parents = []  # Used to store products with missing parents
    total_products_processed = 0    # Used to keep track of the total number of products processed
    delay_seconds = 3  # Set the desired delay between requests in seconds

    while True:
        products = get_product_data(api_key, language, page_size, page_num, bearer_token)
        if not products:
            break

        current_first_item = products[0]
        if previous_first_item and previous_first_item == current_first_item:
            break

        for product in products:
            update_or_create_product(product, products_with_missing_parents, update_hours_threshold)
            total_products_processed += 1
            sleep(delay_seconds)  # Add a delay between requests

        print(f"Page number: {page_num}")
        print(f"Total products processed: {total_products_processed}")
        print(f"Total products with missing parents: {len(products_with_missing_parents)}")

        previous_first_item = current_first_item
        page_num += 1

    # Try to process products with missing parents again
    for product in products_with_missing_parents:
        update_or_create_product(product, [], update_hours_threshold)
        sleep(delay_seconds)  # Add a delay between requests

    print(f"Final page number: {page_num}")
    print(f"Total products processed: {total_products_processed}")
    print(f"Total products with missing parents: {len(products_with_missing_parents)}")

if __name__ == '__main__':
    main()
