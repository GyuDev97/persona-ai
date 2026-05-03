import 'dart:convert';

import 'package:http/http.dart' as http;

class GyuvisApiClient {
  const GyuvisApiClient({required this.baseUrl});

  final String baseUrl;

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  Future<ServerStatus> fetchServerStatus() async {
    final healthResponse = await http.get(_uri('/health'));
    if (healthResponse.statusCode < 200 || healthResponse.statusCode >= 300) {
      throw GyuvisApiException('health ${healthResponse.statusCode}');
    }

    var mode = 'fallback';
    var model = '';
    try {
      final assistantResponse = await http.get(_uri('/assistant/status'));
      if (assistantResponse.statusCode >= 200 && assistantResponse.statusCode < 300) {
        final assistantData = jsonDecode(assistantResponse.body) as Map<String, dynamic>;
        mode = (assistantData['mode'] as String?) ?? mode;
        model = (assistantData['model'] as String?) ?? '';
      }
    } catch (_) {}

    return ServerStatus(mode: mode, model: model);
  }

  Future<AssistantCommandResult> sendAssistantCommand(String text) async {
    final response = await http.post(
      _uri('/mobile/assistant/command'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'text': text, 'source': 'mobile'}),
    );

    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw GyuvisApiException.fromResponse(response);
    }

    final data = jsonDecode(response.body) as Map<String, dynamic>;
    final task = data['task'];
    return AssistantCommandResult(
      summary: (data['summary'] ?? '') as String,
      mode: (data['mode'] ?? 'assistant_reply') as String,
      taskId: task is Map<String, dynamic> ? task['id'] as int? : null,
    );
  }

  Future<AgentTaskStatus> fetchAgentTask(int taskId) async {
    final response = await http.get(_uri('/agent/tasks/$taskId'));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw GyuvisApiException.fromResponse(response);
    }

    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return AgentTaskStatus(
      status: data['status'] as String? ?? 'pending',
      resultSummary: data['result_summary'] as String?,
      errorMessage: data['error_message'] as String?,
    );
  }
}

class ServerStatus {
  const ServerStatus({required this.mode, required this.model});

  final String mode;
  final String model;
}

class AssistantCommandResult {
  const AssistantCommandResult({
    required this.summary,
    required this.mode,
    required this.taskId,
  });

  final String summary;
  final String mode;
  final int? taskId;
}

class AgentTaskStatus {
  const AgentTaskStatus({
    required this.status,
    required this.resultSummary,
    required this.errorMessage,
  });

  final String status;
  final String? resultSummary;
  final String? errorMessage;
}

class GyuvisApiException implements Exception {
  const GyuvisApiException(this.message);

  final String message;

  factory GyuvisApiException.fromResponse(http.Response response) {
    try {
      final data = jsonDecode(response.body);
      if (data is Map<String, dynamic> && data['detail'] != null) {
        return GyuvisApiException(data['detail'].toString());
      }
    } catch (_) {}
    return GyuvisApiException('HTTP ${response.statusCode}: ${response.body}');
  }

  @override
  String toString() => message;
}
