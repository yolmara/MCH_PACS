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
        wadoUriRoot: 'http://localhost:8081/dicomweb',
        qidoRoot: 'http://localhost:8081/dicomweb',
        wadoRoot: 'http://localhost:8081/dicomweb',
        qidoSupportsIncludeField: false,
        imageRendering: 'wadors',
        thumbnailRendering: 'wadors',
      },
    },
  ],
  defaultDataSourceName: 'dicomweb',
};