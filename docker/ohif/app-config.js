const dicomWebRoot = `${window.location.origin}/dicomweb`;

window.config = {
  routerBasename: '/ohif',
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
