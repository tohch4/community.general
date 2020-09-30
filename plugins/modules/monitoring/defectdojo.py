import json
import logging
import os
import pathlib
import traceback
from enum import Enum

import requests
from yaml import safe_load

from defectdojo_api.defectdojo_api import defectdojo_apiv2 as defectdojo

BUFFERSIZE = 65536
DD_ADMIN_USER_ID = 1
DD_ADMIN_PASSWORD = os.getenv("DD_ADMIN_PASSWORD", "admin")
LOGFORMAT = os.getenv("LOGFORMAT", "%(levelname)2s %(message)s")
LOGROOT = os.getenv("LOGROOT", "root")
LOGLEVEL = os.getenv("LOGLEVEL", "INFO").upper()
logging.basicConfig(format=LOGFORMAT)
logger = logging.getLogger(LOGROOT)
logger.setLevel(level=LOGLEVEL)


class ContextFrom(Enum):
    """An enum.Enum class that containers the different context builders that
    are implemented for use in passing sensitive information.
    """
    # @staticmethod
    # def from_none():  # pylint: disable=no-self-argument, no-method-argument
    #     """The default not-implemented context provider, ContextFrom.NONE
    #
    #     :raises: NotImplementedError
    #     """
    #     logger.error("You are using empty context build, which will fail!")
    #     raise NotImplementedError
    #
    # @staticmethod
    # def from_dotenv_file(path=None, vars_map={}):
    #     """Retrieve configuration from a .env file.
    #     """
    #     logger.info("Using from_dotenv_file context builder")
    #     try:
    #         from dotenv import load_dotenv
    #         load_dotenv(path)
    #         # We want to use .env style upper-case variables, but we do not want
    #         # to mangle that stuff in app logic, so use a map to PREFIX_VARNAME
    #         # into varname in a context dictionary to pass back.
    #         return {vars_map[k]: parse_bool(os.getenv(k)) for k in vars_map}
    #     except:
    #         logger.error(
    #             "Failed to load context from dotenv file, set DEBUG for more details")
    #         logger.debug(traceback.format_exc())
    #         return {}
    #
    #
    # @staticmethod
    # def from_yaml_file(path=None):
    #     """Retrieve configuration items from a YAML file.
    #     """
    #     try:
    #         stream = open(path)
    #         markup = safe_load(stream)
    #         logger.debug(markup)
    #         return markup
    #     except:
    #         logger.error("Failed to load '{}', set DEBUG for details".format(path))
    #         logger.debug(traceback.format_exc())
    #         return {}

    # All variables should be passed to the action
    # FROM_NONE = from_none
    # FROM_DOTENV = from_dotenv_file
    # FROM_YAML = from_yaml_file


def parse_bool(value=None):
    """Cast different common truthy and falsey values into correct bool values
    from different string-based context sources. In the case of python-dotenv,
    the library is not capable of serializing any value bound to a variable
    into anything but string. This ensures setting a variable to 1 or true or
    True from string "1" or "true" or "True" values into a proper boolean.
    """
    if (value == True) or (value == "1") or (value == "True") or (value == "true"):
        return True
    elif (value == False) or (value == "0") or (value == "False") or (value == "false"):
        return False
    else:
        return value


def create_context(context_from=None, *args, **kwargs):
    """Gather configuration context to pass build or deployment stages.

    :param context_from: The context builder function requested by this
                         factory. See the ContextFrom enum for options.
    :type context_from: ContextFrom
    :param \*args: Variable length argument list passed to chosen builder
    :param \**kwargs: Arbitrary keyword arguments passed to chosen builder
    :return: An instance of the function (`name`, not `name()`) to be invoked
             later.
    :rtype: function
    """

    logger.debug("Returning '{}' from context builder".format(
        context_from.__name__))
    return context_from(*args, **kwargs)


def get_api_key(context):
    """ Get API key/token for the default user
    If deployed with Terraform, the function fetches the default user's password
    from the AWS Parameter Store to login and get the key. Otherwise, use the
    default password when DefectDojo is provisioned via docker-compose on a
    local development environment
    :param context: The context builder function requested by this
                    factory. See the ContextFrom enum for options.
    """

    password = os.getenv('DD_ADMIN_PASSWORD')

    try:
        url = '{}/api/{}/api-token-auth/?content-type=application/json'.format(
                context.get('host'), context.get('api_version'))
        payload = {'username': context.get('user'), 'password': os.getenv('DD_ADMIN_PASSWORD')}
        response = requests.request("POST", url, data=payload)
        api_key = (json.loads(response.content)).get('token')
        return api_key
    except (ConnectionError, TimeoutError) as ex:
        logger.error(ex)

def create_client(context={}, api_key=None):
    """A factory function to create a DefectDojo API client.
    """
    try:
        params = context.copy()
        host = params.pop("host")
        user = params.pop("user")
        logger.debug("DefectDojo client host: '{}' user: '{}' with opts: '{}'".format(
            host, user, params
        ))
        return defectdojo.DefectDojoAPIv2(host, api_key, user, **params)
    except:
        logger.error(
            "Failed to create DD client, set logging.DEBUG for stack trace")
        logger.debug(traceback.format_exc())


def test_client(client=None):
    """Test DefectDojo client can make a valid connection to the remote server.
    """
    try:
        logger.info("Testing client configuration is valid")
        result = client.get_user(DD_ADMIN_USER_ID)
        return result.success
    except:
        logger.error("Client failed with exception, use DEBUG for details")
        logger.debug(traceback.format_exc())
        raise RuntimeError("Client test failed, exiting")


def get_products(client):
    """Use a DefectDojo client to get existing products
    """
    try:
        result = client.list_products()
        if result.success:
            data = json.loads(result.data_json())
            return data.get("objects", {})
        else:
            logger.error("Error occurred in API call, returning empty response")
            return {}
    except:
        logger.error("Error retrieving existing products, set DEBUG for details")
        logger.debug(traceback.format_exc())


def get_users(client):
    """Use a DefectDojo client to get existing users
    """
    try:
        result = client.list_users()
        if result.success:
            data = json.loads(result.data_json())
            return data.get("objects", {})
        else:
            logger.error("Error occurred in API call, returning empty response")
            return {}
    except:
        logger.error("Error retrieving existing products, set DEBUG for details")
        logger.debug(traceback.format_exc())


def create_product(client, context):
    """Use a DefectDojo client to create a product
    """
    if "products" not in context.keys():
        raise KeyError("Not provided proper products key in context '{}'".format(context))

    allow_existing = context.get("steps").get("create_product").get("allow_existing", False)
    with_items = context.get("steps").get("create_product").get("with_items", "ENOITEMS")
    items = context.get(with_items)
    current = [p.get("name") for p in get_products(client)]

    for i in items:
        try:
            name = i.get("name", "ENOPRODNAME")
            description = i.get("description", "ENOPRODDESCR")
            prod_type = i.get("prod_type", 1)
            account = i.get("account", "none")
            if name in current:
                if allow_existing:
                    logger.info("Product '{}' alread exists, skipping".format(name))
                    continue
                else:
                    raise KeyError("Attempting to add existing item and 'allow_existing' set to False")
            product = client.create_product(name, description, prod_type)
            if product.response_code == 201:
                client.add_product_metadata(product.data['id'],
                                            name='account',
                                            value=account)
            logger.info("Added '{}'".format(i))
        except:
            logger.error("Error in creating new product, set DEBUG for details")
            logger.debug(traceback.format_exc())


def run(*args, **kwargs):
    """The workflow orchestration function that will take a declarative config
    and process steps until complete.
    """
    logger.info("Bootsrapping STARTS")
    try:
        context = create_context(
            ContextFrom.FROM_DOTENV,
            path="{}/.env".format(pathlib.Path(__file__).parent),
            vars_map={
                "DD_HOST": "host",
                "DD_DEBUG": "debug",
                "DD_VERIFY_SSL": "verify_ssl",
                "DD_API_VERSION": "api_version",
                "DD_USER": "user"
            })
    except:
        raise

    api_key = get_api_key(context)
    client = create_client(context, api_key=api_key)
    test_client(client)
    logger.info("Client tested successfully")

    try:
        logger.info("Generating bootstrap config")
        context = create_context(ContextFrom.FROM_YAML, path="{}/bootstrap.yml".format(pathlib.Path(__file__).parent))
    except:
        raise

    try:
        steps = context.get("steps")
        if "create_product" in steps.keys():
            logger.info("Running step 'create_product'")
            create_product(client, context)
    except:
        logger.error("Exception raised in bootstrapping steps, set DEBUG for details")
        logger.debug(traceback.format_exc())

    logger.info("Bootstrapping ENDED")
    print(f"api_key: {api_key}")


if __name__ == "__main__":
    run()
