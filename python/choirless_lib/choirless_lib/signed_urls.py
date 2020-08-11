## Signed URL support
## from https://cloud.ibm.com/docs/cloud-object-storage?topic=cloud-object-storage-presign-url
import datetime
import hashlib
import hmac
import requests
from requests.utils import quote


# hashing methods
def hash(key, msg):
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()


# region is a wildcard value that takes the place of the AWS region value
# as COS doen't use regions like AWS, this parameter can accept any string
def createSignatureKey(key, datestamp, region, service):
    keyDate = hash(('AWS4' + key).encode('utf-8'), datestamp)
    keyRegion = hash(keyDate, region)
    keyService = hash(keyRegion, service)
    keySigning = hash(keyService, 'aws4_request')
    return keySigning


def create_signed_url(host, http_method,
                      access_key, secret_key,
                      region,
                      bucket,
                      object_key):

    expiration = 60 * 60 # 1 hour

    if host.startswith("https://"):
        host = host[8:]

    endpoint = "https://" + host
    
    # assemble the standardized request
    time = datetime.datetime.utcnow()
    timestamp = time.strftime('%Y%m%dT%H%M%SZ')
    datestamp = time.strftime('%Y%m%d')

    standardized_querystring = ( 'X-Amz-Algorithm=AWS4-HMAC-SHA256' +
                                 '&X-Amz-Credential=' + access_key + '/' + datestamp + '/' + region + '/s3/aws4_request' +
                                 '&X-Amz-Date=' + timestamp +
                                 '&X-Amz-Expires=' + str(expiration) +
                                 '&X-Amz-SignedHeaders=host' )
    standardized_querystring_url_encoded = quote(standardized_querystring, safe='&=')

    standardized_resource = '/' + bucket + '/' + object_key
    standardized_resource_url_encoded = quote(standardized_resource, safe='&')

    payload_hash = 'UNSIGNED-PAYLOAD'
    standardized_headers = 'host:' + host
    signed_headers = 'host'

    standardized_request = (http_method + '\n' +
                            standardized_resource + '\n' +
                            standardized_querystring_url_encoded + '\n' +
                            standardized_headers + '\n' +
                            '\n' +
                            signed_headers + '\n' +
                            payload_hash)

    # assemble string-to-sign
    hashing_algorithm = 'AWS4-HMAC-SHA256'
    credential_scope = datestamp + '/' + region + '/' + 's3' + '/' + 'aws4_request'
    sts = ( hashing_algorithm + '\n' +
            timestamp + '\n' +
            credential_scope + '\n' +
            hashlib.sha256(standardized_request.encode('utf-8')).hexdigest() )

    # generate the signature
    signature_key = createSignatureKey(secret_key, datestamp, region, 's3')
    signature = hmac.new(signature_key,
                         (sts).encode('utf-8'),
                         hashlib.sha256).hexdigest()

    # create and send the request
    # the 'requests' package autmatically adds the required 'host' header
    request_url = ( endpoint + '/' +
                    bucket + '/' +
                    object_key + '?' +
                    standardized_querystring_url_encoded +
                    '&X-Amz-Signature=' +
                    signature )

    return request_url
