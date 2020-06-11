# https://github.com/apache/openwhisk/blob/master/docs/actions-docker.md
FROM ibmfunctions/action-nodejs-v10

RUN npm install Choirless/choirlessapi
RUN npm install stitcheroo@1.1.0
RUN npm install ibm-cos-sdk@1.6.1
