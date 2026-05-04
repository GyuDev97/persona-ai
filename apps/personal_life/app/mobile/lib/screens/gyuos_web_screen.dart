import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../config/app_config.dart';

class GyuosWebScreen extends StatefulWidget {
  const GyuosWebScreen({super.key});

  @override
  State<GyuosWebScreen> createState() => _GyuosWebScreenState();
}

class _GyuosWebScreenState extends State<GyuosWebScreen> {
  final TextEditingController _serverController = TextEditingController(text: AppConfig.defaultServerBaseUrl);
  late final WebViewController _webController;
  String _selectedShortcutId = 'money';
  String _selectedPath = '/money-core';
  bool _isLoading = true;

  static const List<_WebShortcut> _shortcuts = [
    _WebShortcut(id: 'money', label: 'Money Core', path: '/money-core', icon: Icons.account_balance_wallet_rounded),
    _WebShortcut(id: 'agent', label: 'Agent Center', path: '/agent/report-center', icon: Icons.hub_rounded),
    _WebShortcut(id: 'home', label: 'GyuOS Home', path: '/briefing.html', icon: Icons.home_rounded),
    _WebShortcut(id: 'briefing', label: 'Briefing', path: '/briefing.html', icon: Icons.today_rounded),
  ];

  @override
  void initState() {
    super.initState();
    _webController = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFF031312))
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: (_) {
            if (mounted) {
              setState(() => _isLoading = true);
            }
          },
          onPageFinished: (_) {
            if (mounted) {
              setState(() => _isLoading = false);
            }
          },
        ),
      );
    _loadSelectedPath();
  }

  @override
  void dispose() {
    _serverController.dispose();
    super.dispose();
  }

  void _loadSelectedPath() {
    final baseUrl = _serverController.text.trim().replaceFirst(RegExp(r'/+$'), '');
    if (baseUrl.isEmpty) {
      return;
    }
    _webController.loadRequest(Uri.parse('$baseUrl$_selectedPath'));
  }

  void _selectShortcut(_WebShortcut shortcut) {
    setState(() {
      _selectedShortcutId = shortcut.id;
      _selectedPath = shortcut.path;
      _isLoading = true;
    });
    _loadSelectedPath();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      backgroundColor: const Color(0xFF031312),
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        'GyuOS Web',
                        style: theme.textTheme.titleLarge?.copyWith(
                          color: const Color(0xFFE8FFF9),
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const Spacer(),
                      IconButton(
                        tooltip: '새로고침',
                        onPressed: _loadSelectedPath,
                        icon: const Icon(Icons.refresh_rounded, color: Color(0xFFA7FFF3)),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    height: 42,
                    child: ListView.separated(
                      scrollDirection: Axis.horizontal,
                      itemCount: _shortcuts.length,
                      separatorBuilder: (_, __) => const SizedBox(width: 8),
                      itemBuilder: (context, index) {
                        final shortcut = _shortcuts[index];
                        final selected = shortcut.id == _selectedShortcutId;
                        return ChoiceChip(
                          selected: selected,
                          avatar: Icon(
                            shortcut.icon,
                            size: 18,
                            color: selected ? const Color(0xFF03211E) : const Color(0xFFA7FFF3),
                          ),
                          label: Text(shortcut.label),
                          labelStyle: TextStyle(
                            color: selected ? const Color(0xFF03211E) : const Color(0xFFD5FFF8),
                            fontWeight: FontWeight.w700,
                          ),
                          selectedColor: const Color(0xFF7CEADD),
                          backgroundColor: const Color(0x1A7CEADD),
                          side: const BorderSide(color: Color(0x3348CFC2)),
                          onSelected: (_) => _selectShortcut(shortcut),
                        );
                      },
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: _serverController,
                    onSubmitted: (_) => _loadSelectedPath(),
                    style: const TextStyle(color: Color(0xFFE8FFF9)),
                    decoration: InputDecoration(
                      isDense: true,
                      prefixIcon: const Icon(Icons.dns_rounded, color: Color(0xFF92FFF1)),
                      suffixIcon: IconButton(
                        tooltip: '이 주소로 열기',
                        onPressed: _loadSelectedPath,
                        icon: const Icon(Icons.arrow_forward_rounded, color: Color(0xFFA7FFF3)),
                      ),
                      labelText: 'PC 서버 주소',
                      labelStyle: const TextStyle(color: Color(0xFF8CB9B3)),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(16),
                        borderSide: const BorderSide(color: Color(0x3348CFC2)),
                      ),
                      focusedBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(16),
                        borderSide: const BorderSide(color: Color(0xFF48CFC2)),
                      ),
                      filled: true,
                      fillColor: const Color(0x220C2B29),
                    ),
                  ),
                ],
              ),
            ),
            Expanded(
              child: Stack(
                children: [
                  WebViewWidget(controller: _webController),
                  if (_isLoading)
                    const LinearProgressIndicator(
                      minHeight: 2,
                      backgroundColor: Color(0x220C2B29),
                      color: Color(0xFF7CEADD),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _WebShortcut {
  const _WebShortcut({
    required this.id,
    required this.label,
    required this.path,
    required this.icon,
  });

  final String id;
  final String label;
  final String path;
  final IconData icon;
}
