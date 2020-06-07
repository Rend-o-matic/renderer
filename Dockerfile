# https://github.com/apache/openwhisk/blob/master/docs/actions-docker.md
FROM ibmfunctions/action-nodejs-v10

RUN npm install Choirless/choirlessapi
RUN npm install stitcheroo
RUN npm install ibm-cos-sdk

#RUN cp -r node_modules/* /node_modules
#RUN rm -rf node_modules
#RUN tar -czvf deps.tar.gz node_modules/
#COPY index.js .
#CMD [ "node", "index.js" ]