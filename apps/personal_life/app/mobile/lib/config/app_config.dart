class AppConfig {
  const AppConfig._();

  static const defaultServerBaseUrl = String.fromEnvironment(
    'GYUVIS_SERVER_URL',
    defaultValue: 'http://192.168.0.19:8000',
  );
}
