class SpeechTextFormatter {
  const SpeechTextFormatter._();

  static String normalizeTranscript(String value) {
    var text = value.trim();
    if (text.isEmpty) {
      return text;
    }

    final looksLikeQuestion = [
      '있나',
      '있어',
      '있지',
      '어때',
      '어떨까',
      '뭐야',
      '뭐지',
      '뭐가',
      '뭐부터',
      '할까',
      '말까',
      '일까',
      '인가',
      '맞나',
      '되나',
      '되려나',
      '흐름이 어떻게 돼',
      '상황이 어때',
    ].any((pattern) => text.endsWith(pattern) || text.contains('$pattern '));

    if (looksLikeQuestion && !text.endsWith('?')) {
      text = '$text?';
    }

    return text;
  }

  static String chooseBetterCandidate(String current, String incoming) {
    final currentText = current.trim();
    final incomingText = incoming.trim();
    if (incomingText.isEmpty) {
      return currentText;
    }
    if (currentText.isEmpty) {
      return incomingText;
    }
    if (incomingText.length >= currentText.length + 2) {
      return incomingText;
    }
    if (incomingText.endsWith('?') && !currentText.endsWith('?')) {
      return incomingText;
    }
    if (_looksMoreComplete(currentText, incomingText)) {
      return incomingText;
    }
    return currentText;
  }

  static String speakFriendly(String text) {
    var value = text.trim();
    if (value.isEmpty) {
      return value;
    }

    value = value
        .replaceAll("'", '')
        .replaceAll('"', '')
        .replaceAll('%', ' 퍼센트')
        .replaceAll('·', ', ')
        .replaceAll('\n\n', '. ')
        .replaceAll('\n', '. ')
        .replaceAllMapped(RegExp(r'(\d+)\.'), (match) => '${match.group(1)}번, ')
        .replaceAllMapped(RegExp(r'\s+'), (match) => ' ');

    final sentences = value
        .split('. ')
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toList();

    if (sentences.length > 2) {
      value = '${sentences.take(2).join('. ')}.';
    } else {
      value = sentences.join('. ');
      if (!value.endsWith('.')) {
        value = '$value.';
      }
    }

    if (value.length > 140) {
      value = '${value.substring(0, 140).trim()}...';
    }

    return value.replaceAll('..', '.').trim();
  }

  static bool _looksMoreComplete(String current, String incoming) {
    if (incoming.length <= current.length) {
      return false;
    }
    final completionSignals = ['어때', '어떨까', '뭐야', '뭐지', '가능해', '할 수', '있나', '맞아', '?'];
    final incomingHasSignal = completionSignals.any((token) => incoming.contains(token));
    final currentHasSignal = completionSignals.any((token) => current.contains(token));
    return incomingHasSignal && !currentHasSignal;
  }
}
