const protocol = window.location.protocol || 'http:';
const hostname = window.location.hostname || 'localhost';
const dicomWebRoot = `${protocol}//${hostname}:8081/dicomweb`;

window.config = {
  routerBasename: '/',
  showStudyList: true,
  extensions: [],
  modes: [],
  dataSources: [
    {
      namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
      sourceName: 'dicomweb',
      configuration: {
        friendlyName: 'MCH PACS',
        name: 'dicomweb',
        wadoUriRoot: dicomWebRoot,
        qidoRoot: dicomWebRoot,
        wadoRoot: dicomWebRoot,
        qidoSupportsIncludeField: false,
        imageRendering: 'wadors',
        thumbnailRendering: 'wadors',
      },
    },
  ],
  defaultDataSourceName: 'dicomweb',
};
