import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;

import 'config/app_config.dart';
import 'models/chat_bubble_data.dart';
import 'services/gyuvis_api_client.dart';
import 'services/speech_text_formatter.dart';
import 'widgets/core_action_button.dart';
import 'widgets/core_orb.dart';
import 'widgets/quick_prompt_chip.dart';
import 'widgets/status_chip.dart';

void main() {
  runApp(const GyuvisApp());
}

class GyuvisApp extends StatelessWidget {
  const GyuvisApp({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = ThemeData(
      useMaterial3: true,
      fontFamily: 'Malgun Gothic',
      colorScheme: ColorScheme.fromSeed(
        seedColor: const Color(0xFF29D7C4),
        brightness: Brightness.dark,
      ),
      scaffoldBackgroundColor: const Color(0xFF031312),
    );

    return MaterialApp(
      title: '규비스',
      debugShowCheckedModeBanner: false,
      theme: theme,
      home: const AssistantHomePage(),
    );
  }
}

class AssistantHomePage extends StatefulWidget {
  const AssistantHomePage({super.key});

  @override
  State<AssistantHomePage> createState() => _AssistantHomePageState();
}

class _AssistantHomePageState extends State<AssistantHomePage> with SingleTickerProviderStateMixin {
  final TextEditingController _serverController = TextEditingController(text: AppConfig.defaultServerBaseUrl);
  final TextEditingController _inputController = TextEditingController();
  final stt.SpeechToText _speechToText = stt.SpeechToText();
  final FlutterTts _tts = FlutterTts();
  final List<ChatBubbleData> _messages = <ChatBubbleData>[
    const ChatBubbleData(
      role: BubbleRole.assistant,
      text: '안녕하세요 보스. 어떤 걸 도와드릴까요?',
    ),
  ];

  Timer? _pollTimer;
  Timer? _wakeResumeTimer;
  Timer? _voiceFinalizeTimer;
  Timer? _serverStatusTimer;
  bool _isListening = false;
  bool _isAmbientListening = false;
  bool _speechReady = false;
  bool _speakReplies = true;
  bool _isSpeaking = false;
  bool _isBusy = false;
  bool _clapWakeEnabled = true;
  bool _wakeHandling = false;
  bool _voiceFinalReady = false;
  bool _voiceSubmitDispatched = false;
  bool _serverOnline = false;
  String _serverMode = 'unknown';
  String _serverStatusMessage = '서버 상태 확인 전';
  String _bestVoiceNormalized = '';
  String _lastVoiceRaw = '';
  String _lastVoiceNormalized = '';
  String _statusText = '대기 중';
  int? _pendingTaskId;
  late final AnimationController _coreController;
  final List<DateTime> _clapPeaks = <DateTime>[];
  DateTime _suppressWakeUntil = DateTime.now().add(const Duration(seconds: 4));

  @override
  void initState() {
    super.initState();
    _coreController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 8),
    )..repeat();
    _initTts();
    _startServerStatusPolling();
    unawaited(_initSpeechAndWakeMode());
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _wakeResumeTimer?.cancel();
    _voiceFinalizeTimer?.cancel();
    _serverStatusTimer?.cancel();
    _serverController.dispose();
    _inputController.dispose();
    _coreController.dispose();
    unawaited(_speechToText.stop());
    _tts.stop();
    super.dispose();
  }

  Future<void> _initTts() async {
    await _tts.setLanguage('ko-KR');
    await _tts.awaitSpeakCompletion(true);
    await _tts.setSpeechRate(0.55);
    await _tts.setPitch(1.04);
    await _tts.setVolume(1.0);
    await _speak(_messages.first.text);
    _suppressWakeUntil = DateTime.now().add(const Duration(seconds: 2));
    _scheduleWakeResume(immediate: true);
  }

  void _startServerStatusPolling() {
    unawaited(_refreshServerStatus());
    _serverStatusTimer?.cancel();
    _serverStatusTimer = Timer.periodic(
      const Duration(seconds: 20),
      (_) => unawaited(_refreshServerStatus()),
    );
  }

  Future<void> _refreshServerStatus() async {
    final baseUrl = _serverController.text.trim();
    if (baseUrl.isEmpty) {
      if (!mounted) return;
      setState(() {
        _serverOnline = false;
        _serverMode = 'unknown';
        _serverStatusMessage = '서버 주소가 비어 있습니다.';
      });
      return;
    }

    try {
      final status = await GyuvisApiClient(baseUrl: baseUrl).fetchServerStatus();

      if (!mounted) return;
      setState(() {
        _serverOnline = true;
        _serverMode = status.mode;
        _serverStatusMessage = status.mode == 'openai' ? 'AI 응답 준비 완료' : '기본 응답 모드 연결';
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _serverOnline = false;
        _serverMode = 'offline';
        _serverStatusMessage = '서버 연결을 확인해 주세요.';
      });
    }
  }

  Future<void> _initSpeechAndWakeMode() async {
    final available = await _speechToText.initialize(
      onStatus: _handleSpeechStatus,
      onError: (error) {
        if (!mounted) return;
        setState(() {
          _isListening = false;
          _isAmbientListening = false;
          _statusText = '호출 대기를 다시 맞추는 중입니다.';
        });
        _scheduleWakeResume();
      },
    );

    if (!mounted) return;
    setState(() {
      _speechReady = available;
      if (!available) {
        _clapWakeEnabled = false;
        _statusText = '이 기기에서는 음성 인식을 사용할 수 없습니다.';
      }
    });

  }

  Future<void> _toggleListening() async {
    if (_isListening) {
      await _speechToText.stop();
      setState(() {
        _isListening = false;
        _statusText = '음성 입력을 멈췄습니다.';
      });
      _scheduleWakeResume();
      return;
    }

    if (!_speechReady) {
      setState(() {
        _statusText = '이 기기에서는 음성 인식을 사용할 수 없습니다.';
      });
      return;
    }

    await _startVoiceListening();
  }

  Future<void> _startVoiceListening() async {
    _wakeResumeTimer?.cancel();
    _voiceFinalizeTimer?.cancel();
    _voiceFinalReady = false;
    _voiceSubmitDispatched = false;
    _bestVoiceNormalized = '';
    if (_speechToText.isListening) {
      await _speechToText.stop();
    }

    setState(() {
      _isListening = true;
      _isAmbientListening = false;
      _statusText = '듣고 있어요. 말씀해주세요.';
    });

    await _speechToText.listen(
      localeId: 'ko_KR',
      partialResults: true,
      cancelOnError: false,
      listenMode: stt.ListenMode.dictation,
      pauseFor: const Duration(seconds: 10),
      listenFor: const Duration(seconds: 90),
      onResult: (result) {
        final normalized = SpeechTextFormatter.normalizeTranscript(result.recognizedWords);
        final bestNormalized = SpeechTextFormatter.chooseBetterCandidate(_bestVoiceNormalized, normalized);
        _bestVoiceNormalized = bestNormalized;
        debugPrint('[Gyuvis][voice][raw] ${result.recognizedWords}');
        debugPrint('[Gyuvis][voice][normalized] $normalized');
        debugPrint('[Gyuvis][voice][best] $_bestVoiceNormalized');
        setState(() {
          _lastVoiceRaw = result.recognizedWords;
          _lastVoiceNormalized = bestNormalized;
          _inputController.text = bestNormalized;
          _inputController.selection = TextSelection.fromPosition(
            TextPosition(offset: _inputController.text.length),
          );
        });
        if (result.finalResult) {
          _voiceFinalizeTimer?.cancel();
          _voiceFinalReady = true;
          _voiceSubmitDispatched = true;
          _isListening = false;
          _statusText = '음성을 텍스트로 옮겼습니다.';
          unawaited(_submitCommand());
        }
      },
    );
  }

  Future<void> _submitCommand([String? preset]) async {
    final candidateText = preset ?? (_bestVoiceNormalized.isNotEmpty ? _bestVoiceNormalized : _inputController.text);
    final text = candidateText.trim();
    if (text.isEmpty || _isBusy) {
      return;
    }
    debugPrint('[Gyuvis][submit] $text');
    var shouldResumeListening = false;
    unawaited(_refreshServerStatus());

    _pollTimer?.cancel();
    setState(() {
      _isBusy = true;
      _pendingTaskId = null;
      _statusText = '서버에 명령을 보내는 중입니다.';
      _messages.add(ChatBubbleData(role: BubbleRole.user, text: text));
    });
    unawaited(_speak('잠시만 기다려주세요.'));

    try {
      final result = await GyuvisApiClient(
        baseUrl: _serverController.text.trim(),
      ).sendAssistantCommand(text);

      setState(() {
        _messages.add(ChatBubbleData(role: BubbleRole.assistant, text: result.summary));
        _statusText = result.mode == 'agent_task'
            ? 'PC 에이전트가 작업을 시작했습니다.'
            : '응답을 받았습니다.';
      });

      _inputController.clear();
      await _speak(result.summary);

      if (result.mode == 'agent_task' && result.taskId != null) {
        setState(() {
          _pendingTaskId = result.taskId;
        });
        _startPollingTask(result.taskId!);
      } else {
        shouldResumeListening = true;
      }
    } catch (error) {
      setState(() {
        _messages.add(ChatBubbleData(role: BubbleRole.assistant, text: '요청 처리 중 문제가 생겼습니다.\n\n$error'));
        _statusText = '오류가 발생했습니다.';
      });
    } finally {
      setState(() {
        _isBusy = false;
      });
      if (shouldResumeListening) {
        _resumeConversationListening();
      } else {
        _scheduleWakeResume();
      }
    }
  }

  void _startPollingTask(int taskId) {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(seconds: 2), (_) => _pollTask(taskId));
  }

  Future<void> _pollTask(int taskId) async {
    try {
      final task = await GyuvisApiClient(
        baseUrl: _serverController.text.trim(),
      ).fetchAgentTask(taskId);
      if (!mounted) return;

      if (task.status == 'completed') {
        _pollTimer?.cancel();
        final resultSummary = task.resultSummary ?? '작업은 끝났는데 결과 요약이 비어 있습니다.';
        setState(() {
          _pendingTaskId = null;
          _messages.add(ChatBubbleData(role: BubbleRole.assistant, text: resultSummary));
          _statusText = 'PC 에이전트가 작업을 끝냈습니다.';
        });
        await _speak(resultSummary);
        _resumeConversationListening();
        return;
      }

      if (task.status == 'failed') {
        _pollTimer?.cancel();
        final message = task.errorMessage ?? 'PC 에이전트 작업이 실패했습니다.';
        setState(() {
          _pendingTaskId = null;
          _messages.add(ChatBubbleData(role: BubbleRole.assistant, text: 'PC 작업 중 문제가 생겼습니다.\n\n$message'));
          _statusText = 'PC 작업이 실패했습니다.';
        });
        return;
      }

      setState(() {
        _statusText = 'PC 에이전트가 아직 작업 중입니다.';
      });
    } catch (error) {
      setState(() {
        _statusText = '작업 상태 확인 중 문제가 생겼습니다.';
      });
    }
  }

  Future<void> _speak(String text) async {
    if (!_speakReplies) return;
    final speakText = SpeechTextFormatter.speakFriendly(text);
    if (mounted) {
      setState(() {
        _isSpeaking = true;
      });
    }
    try {
      await _tts.stop();
      await _tts.speak(speakText);
    } finally {
      if (mounted) {
        setState(() {
          _isSpeaking = false;
        });
      }
    }
  }

void _handleSpeechStatus(String status) {
    if (!mounted) return;
    if (status == 'done' || status == 'notListening') {
      final hasDraftCommand = _inputController.text.trim().isNotEmpty;
      if (_isListening || _isAmbientListening) {
        setState(() {
          _isListening = false;
          _isAmbientListening = false;
        });
      }
      if (hasDraftCommand && !_isBusy && _pendingTaskId == null) {
        if (_voiceFinalReady && !_voiceSubmitDispatched) {
          _voiceSubmitDispatched = true;
          unawaited(_submitCommand());
          return;
        }
        if (!_voiceFinalReady && !_voiceSubmitDispatched) {
          _voiceFinalizeTimer?.cancel();
          _voiceFinalizeTimer = Timer(const Duration(milliseconds: 900), () {
            if (!mounted || _isBusy || _pendingTaskId != null || _voiceSubmitDispatched) {
              return;
            }
            if (_inputController.text.trim().isEmpty) {
              _scheduleWakeResume();
              return;
            }
            _voiceSubmitDispatched = true;
            unawaited(_submitCommand());
          });
          return;
        }
        return;
      }
      _scheduleWakeResume();
    }
  }

  void _scheduleWakeResume({bool immediate = false}) {
    if (!_clapWakeEnabled || !_speechReady || _isListening || _isBusy || _pendingTaskId != null || _wakeHandling) {
      return;
    }
    _wakeResumeTimer?.cancel();
    _wakeResumeTimer = Timer(immediate ? Duration.zero : const Duration(milliseconds: 900), () {
      unawaited(_startAmbientClapListening());
    });
  }

  Future<void> _startAmbientClapListening() async {
    if (!_clapWakeEnabled || !_speechReady || _isListening || _isBusy || _pendingTaskId != null || _wakeHandling) {
      return;
    }
    if (_speechToText.isListening) {
      await _speechToText.stop();
    }

    setState(() {
      _isAmbientListening = true;
      _statusText = '박수 호출 대기 중입니다.';
    });

    _clapPeaks.clear();
    await _speechToText.listen(
      localeId: 'ko_KR',
      partialResults: false,
      cancelOnError: false,
      pauseFor: const Duration(seconds: 8),
      listenFor: const Duration(seconds: 120),
      onResult: (_) {},
      onSoundLevelChange: _handleSoundLevel,
    );
  }

  void _handleSoundLevel(double level) {
    if (!_clapWakeEnabled || !_isAmbientListening || _wakeHandling) {
      return;
    }
    if (DateTime.now().isBefore(_suppressWakeUntil)) {
      return;
    }
    if (level < 8.5) {
      return;
    }

    final now = DateTime.now();
    if (_clapPeaks.isNotEmpty && now.difference(_clapPeaks.last).inMilliseconds < 220) {
      return;
    }

    _clapPeaks.add(now);
    _clapPeaks.removeWhere((item) => now.difference(item).inMilliseconds > 1200);

    if (_clapPeaks.length >= 2) {
      final gap = _clapPeaks.last.difference(_clapPeaks[_clapPeaks.length - 2]).inMilliseconds;
      if (gap >= 180 && gap <= 1100) {
        _clapPeaks.clear();
        unawaited(_triggerBossWake());
      }
    }
  }

  Future<void> _triggerBossWake() async {
    if (_wakeHandling) return;
    _wakeHandling = true;
    _wakeResumeTimer?.cancel();

    if (_speechToText.isListening) {
      await _speechToText.stop();
    }

    if (!mounted) return;
    setState(() {
      _isAmbientListening = false;
      _isListening = false;
      _statusText = '호출 감지됨';
    });

    _suppressWakeUntil = DateTime.now().add(const Duration(seconds: 3));
    await _speak('네, 보스.');
    await Future<void>.delayed(const Duration(milliseconds: 240));

    _wakeHandling = false;
    if (_speechReady) {
      await _startVoiceListening();
    }
  }

  void _resumeConversationListening() {
    if (!_speechReady || _isBusy || _pendingTaskId != null) {
      _scheduleWakeResume();
      return;
    }
    _wakeResumeTimer?.cancel();
    _suppressWakeUntil = DateTime.now().add(const Duration(milliseconds: 800));
    Future<void>.delayed(const Duration(milliseconds: 450), () {
      if (!mounted || _isListening || _isBusy || _pendingTaskId != null) {
        return;
      }
      unawaited(_startVoiceListening());
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final latestAssistantMessage = _messages.lastWhere(
      (message) => message.role == BubbleRole.assistant,
      orElse: () => const ChatBubbleData(role: BubbleRole.assistant, text: '규비스 대기 중입니다.'),
    );

    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: RadialGradient(
            center: Alignment(0, -0.2),
            radius: 1.1,
            colors: [
              Color(0xFF0D3835),
              Color(0xFF061D1C),
              Color(0xFF020908),
            ],
          ),
        ),
        child: SafeArea(
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
                child: Row(
                  children: [
                    Text(
                      'GYUVIS',
                      style: theme.textTheme.labelLarge?.copyWith(
                        color: const Color(0xFF7CEADD),
                        letterSpacing: 3,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const Spacer(),
                    IconButton(
                      onPressed: () {
                        setState(() {
                          _speakReplies = !_speakReplies;
                        });
                      },
                      icon: Icon(
                        _speakReplies ? Icons.volume_up_rounded : Icons.volume_off_rounded,
                        color: const Color(0xFFA7FFF3),
                      ),
                    ),
                    IconButton(
                      onPressed: () {
                        unawaited(_refreshServerStatus());
                      },
                      icon: const Icon(
                        Icons.cloud_sync_rounded,
                        color: Color(0xFFA7FFF3),
                      ),
                    ),
                    IconButton(
                      onPressed: () async {
                        setState(() {
                          _clapWakeEnabled = !_clapWakeEnabled;
                          _statusText = _clapWakeEnabled ? '박수 호출을 다시 켰습니다.' : '박수 호출을 껐습니다.';
                        });
                        if (_clapWakeEnabled) {
                          _scheduleWakeResume(immediate: true);
                        } else {
                          _wakeResumeTimer?.cancel();
                          await _speechToText.stop();
                          if (mounted) {
                            setState(() {
                              _isAmbientListening = false;
                              _isListening = false;
                            });
                          }
                        }
                      },
                      icon: Icon(
                        _clapWakeEnabled ? Icons.back_hand_rounded : Icons.back_hand_outlined,
                        color: const Color(0xFFA7FFF3),
                      ),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: SingleChildScrollView(
                  physics: const BouncingScrollPhysics(),
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Builder(
                    builder: (context) {
                      final screenWidth = MediaQuery.of(context).size.width;
                      final coreSize = screenWidth * 0.62;
                      return Center(
                        child: Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 12),
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              AnimatedBuilder(
                                animation: _coreController,
                                builder: (context, child) {
                                  final glow = 0.72 + (_coreController.value * 0.28);
                                    return Transform.scale(
                                     scale: 0.96 + (_coreController.value * 0.03),
                                     child: CoreOrb(
                                       size: coreSize.clamp(200.0, 340.0),
                                        glowOpacity: glow,
                                       animationValue: _coreController.value,
                                        isListening: _isListening,
                                        isBusy: _isBusy || _pendingTaskId != null,
                                        isSpeaking: _isSpeaking,
                                      ),
                                    );
                                  },
                              ),
                              const SizedBox(height: 24),
                              Text(
                                _statusHeadline(),
                                style: theme.textTheme.headlineSmall?.copyWith(
                                  color: const Color(0xFFE8FFF9),
                                  fontWeight: FontWeight.w700,
                                ),
                                textAlign: TextAlign.center,
                              ),
                              const SizedBox(height: 12),
                              Padding(
                                padding: const EdgeInsets.symmetric(horizontal: 16),
                                child: Text(
                                  latestAssistantMessage.text,
                                  maxLines: 4,
                                  overflow: TextOverflow.ellipsis,
                                  style: theme.textTheme.bodyLarge?.copyWith(
                                    color: const Color(0xFFA8D4CE),
                                    height: 1.6,
                                  ),
                                  textAlign: TextAlign.center,
                                ),
                              ),
                              const SizedBox(height: 18),
                              Container(
                                width: double.infinity,
                                margin: const EdgeInsets.symmetric(horizontal: 12),
                                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                                decoration: BoxDecoration(
                                  color: const Color(0x120FFFF0),
                                  borderRadius: BorderRadius.circular(18),
                                  border: Border.all(color: const Color(0x2248CFC2)),
                                ),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      '서버 상태',
                                      style: theme.textTheme.labelLarge?.copyWith(
                                        color: const Color(0xFF92FFF1),
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                    const SizedBox(height: 10),
                                    Wrap(
                                      spacing: 8,
                                      runSpacing: 8,
                                      children: [
                                        StatusChip(
                                          icon: _serverOnline ? Icons.wifi_tethering_rounded : Icons.portable_wifi_off_rounded,
                                          label: _serverOnline ? '연결됨' : '오프라인',
                                          color: _serverOnline ? const Color(0xFF7CEADD) : const Color(0xFFFFB4A2),
                                        ),
                                        StatusChip(
                                          icon: Icons.smart_toy_outlined,
                                          label: _serverMode == 'openai' ? 'AI 응답' : '기본 응답',
                                          color: const Color(0xFFA7FFF3),
                                        ),
                                       
                                      ],
                                    ),
                                    const SizedBox(height: 10),
                                    Text(
                                      _serverStatusMessage,
                                      style: theme.textTheme.bodySmall?.copyWith(
                                        color: const Color(0xFFC7F7EF),
                                        height: 1.45,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              if (_lastVoiceRaw.isNotEmpty || _lastVoiceNormalized.isNotEmpty) ...[
                                const SizedBox(height: 18),
                                Container(
                                  width: double.infinity,
                                  margin: const EdgeInsets.symmetric(horizontal: 12),
                                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                                  decoration: BoxDecoration(
                                    color: const Color(0x140FFFF0),
                                    borderRadius: BorderRadius.circular(18),
                                    border: Border.all(color: const Color(0x2248CFC2)),
                                  ),
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        '음성 로그',
                                        style: theme.textTheme.labelLarge?.copyWith(
                                          color: const Color(0xFF92FFF1),
                                          fontWeight: FontWeight.w700,
                                        ),
                                      ),
                                      const SizedBox(height: 8),
                                      Text(
                                        '원본: ${_lastVoiceRaw.isEmpty ? '-' : _lastVoiceRaw}',
                                        style: theme.textTheme.bodySmall?.copyWith(
                                          color: const Color(0xFFC7F7EF),
                                          height: 1.45,
                                        ),
                                      ),
                                      const SizedBox(height: 6),
                                      Text(
                                        '전송: ${_lastVoiceNormalized.isEmpty ? '-' : _lastVoiceNormalized}',
                                        style: theme.textTheme.bodySmall?.copyWith(
                                          color: const Color(0xFFE8FFF9),
                                          fontWeight: FontWeight.w600,
                                          height: 1.45,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                              const SizedBox(height: 24),
                              Wrap(
                                alignment: WrapAlignment.center,
                                spacing: 12,
                                runSpacing: 12,
                                children: [
                                  CoreActionButton(
                                    icon: _isListening ? Icons.mic_off_rounded : Icons.mic_rounded,
                                    label: _isListening ? '듣기 중지' : '말하기',
                                    onTap: _toggleListening,
                                    accent: true,
                                  ),
                                  CoreActionButton(
                                    icon: Icons.keyboard_outlined,
                                    label: '텍스트',
                                    onTap: _openCommandSheet,
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(18, 0, 18, 18),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                  decoration: BoxDecoration(
                    color: const Color(0x2217FFF0),
                    borderRadius: BorderRadius.circular(22),
                    border: Border.all(color: const Color(0x227CEADD)),
                  ),
                  child: Wrap(
                    crossAxisAlignment: WrapCrossAlignment.center,
                    spacing: 10,
                    runSpacing: 6,
                    children: [
                      const Icon(Icons.graphic_eq_rounded, color: Color(0xFF92FFF1)),
                      Text(
                        _statusText,
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: const Color(0xFFC7F7EF),
                        ),
                      ),
                      Text(
                        _clapWakeEnabled ? '박수 호출 켜짐' : '박수 호출 꺼짐',
                        style: theme.textTheme.labelMedium?.copyWith(
                          color: const Color(0xFF92FFF1),
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _statusHeadline() {
    if (_isListening) {
      return '듣고 있습니다';
    }
    if (_pendingTaskId != null || _isBusy) {
      return '확인 중입니다';
    }
    if (_isAmbientListening && _clapWakeEnabled) {
      return '호출 대기 중';
    }
    return '규비스 준비 완료';
  }

  Future<void> _openCommandSheet() async {
    final theme = Theme.of(context);
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF081918),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (context) {
        return Padding(
          padding: EdgeInsets.fromLTRB(
            18,
            18,
            18,
            18 + MediaQuery.of(context).viewInsets.bottom,
          ),
          child: StatefulBuilder(
            builder: (context, setModalState) {
              return Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '규비스 직접 명령',
                    style: theme.textTheme.titleLarge?.copyWith(
                      color: const Color(0xFFE8FFF9),
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    controller: _serverController,
                    onChanged: (_) {
                      unawaited(_refreshServerStatus());
                    },
                    style: const TextStyle(color: Color(0xFFE8FFF9)),
                    decoration: _sheetInputDecoration('서버 주소', '예: http://192.168.0.19:8000'),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _inputController,
                    minLines: 2,
                    maxLines: 4,
                    style: const TextStyle(color: Color(0xFFE8FFF9)),
                    decoration: _sheetInputDecoration('명령 입력', '예: 최신 뉴스 요약해줘'),
                  ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      QuickPromptChip(
                        label: '최신 뉴스',
                        onTap: () {
                          _inputController.text = '최신 뉴스 요약해줘';
                          setModalState(() {});
                        },
                      ),
                      QuickPromptChip(
                        label: '내일 날씨',
                        onTap: () {
                          _inputController.text = '내일 날씨 알려줘';
                          setModalState(() {});
                        },
                      ),
                      QuickPromptChip(
                        label: '오늘 할 일',
                        onTap: () {
                          _inputController.text = '오늘 내가 해야 할 거 뭐 있어?';
                          setModalState(() {});
                        },
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: _isBusy
                          ? null
                          : () {
                              Navigator.of(context).pop();
                              _submitCommand();
                            },
                      style: FilledButton.styleFrom(
                        backgroundColor: const Color(0xFF1CCAB8),
                        foregroundColor: const Color(0xFF03211E),
                        padding: const EdgeInsets.symmetric(vertical: 14),
                      ),
                      child: Text(_isBusy ? '전송 중' : '명령 보내기'),
                    ),
                  ),
                  const SizedBox(height: 8),
                ],
              );
            },
          ),
        );
      },
    );
  }

  InputDecoration _sheetInputDecoration(String label, String hint) {
    return InputDecoration(
      labelText: label,
      hintText: hint,
      labelStyle: const TextStyle(color: Color(0xFF8CB9B3)),
      hintStyle: const TextStyle(color: Color(0xFF5F8A85)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: const BorderSide(color: Color(0x3348CFC2)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(18),
        borderSide: const BorderSide(color: Color(0xFF48CFC2)),
      ),
      filled: true,
      fillColor: const Color(0x220C2B29),
    );
  }
}


