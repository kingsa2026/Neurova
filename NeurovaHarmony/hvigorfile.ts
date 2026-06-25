// 鸿蒙工程构建脚本 - HarmonyOS 6.1 (API 13)
export default app => {
  app.overrideSigningConfig('default', {
    type: 'HarmonyOS',
    material: {
      certpath: '',
      storePassword: '',
      keyAlias: '',
      keyPassword: '',
      profile: '',
      signAlg: 'SHA256withECDSA',
      storeFile: ''
    }
  });
};
