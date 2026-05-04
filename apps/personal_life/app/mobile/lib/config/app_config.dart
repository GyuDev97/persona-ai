class AppConfig {
  const AppConfig._();

  static const defaultServerBaseUrl = String.fromEnvironment(
    'GYUVIS_SERVER_URL',
    defaultValue: 'http://53.92.32.20:8000',
  );
}
