import 'dart:async';

import 'package:flutter/material.dart';

import '../config/app_config.dart';
import '../services/gyuvis_api_client.dart';

class AgentReportScreen extends StatefulWidget {
  const AgentReportScreen({super.key});

  @override
  State<AgentReportScreen> createState() => _AgentReportScreenState();
}

class _AgentReportScreenState extends State<AgentReportScreen> {
  final TextEditingController _serverController = TextEditingController(text: AppConfig.defaultServerBaseUrl);
  late Future<Map<String, dynamic>> _reportFuture;

  @override
  void initState() {
    super.initState();
    _reportFuture = _fetchReport();
  }

  @override
  void dispose() {
    _serverController.dispose();
    super.dispose();
  }

  Future<Map<String, dynamic>> _fetchReport() {
    return GyuvisApiClient(baseUrl: _cleanBaseUrl()).fetchAgentReportCenter();
  }

  String _cleanBaseUrl() => _serverController.text.trim().replaceFirst(RegExp(r'/+$'), '');

  void _reload() {
    setState(() {
      _reportFuture = _fetchReport();
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      backgroundColor: const Color(0xFF090807),
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
                        'Agent 리포트',
                        style: theme.textTheme.titleLarge?.copyWith(
                          color: const Color(0xFFFFF7EF),
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const Spacer(),
                      IconButton(
                        tooltip: '새로고침',
                        onPressed: _reload,
                        icon: const Icon(Icons.refresh_rounded, color: Color(0xFFFFB36A)),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: _serverController,
                    onSubmitted: (_) => _reload(),
                    style: const TextStyle(color: Color(0xFFFFF7EF)),
                    decoration: InputDecoration(
                      isDense: true,
                      prefixIcon: const Icon(Icons.dns_rounded, color: Color(0xFFFFB36A)),
                      suffixIcon: IconButton(
                        tooltip: '이 주소로 조회',
                        onPressed: _reload,
                        icon: const Icon(Icons.arrow_forward_rounded, color: Color(0xFFFFD2A6)),
                      ),
                      labelText: 'PC 서버 주소',
                      labelStyle: const TextStyle(color: Color(0xFFC6A891)),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(16),
                        borderSide: const BorderSide(color: Color(0x33FFB36A)),
                      ),
                      focusedBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(16),
                        borderSide: const BorderSide(color: Color(0xFFFFB36A)),
                      ),
                      filled: true,
                      fillColor: const Color(0x22FFD2A6),
                    ),
                  ),
                ],
              ),
            ),
            Expanded(
              child: FutureBuilder<Map<String, dynamic>>(
                future: _reportFuture,
                builder: (context, snapshot) {
                  if (snapshot.connectionState == ConnectionState.waiting) {
                    return const Center(
                      child: CircularProgressIndicator(color: Color(0xFFFFB36A)),
                    );
                  }
                  if (snapshot.hasError) {
                    return _ErrorView(message: snapshot.error.toString(), onRetry: _reload);
                  }
                  return _ReportBody(
                    data: snapshot.data ?? const <String, dynamic>{},
                    baseUrl: _cleanBaseUrl(),
                    onRefresh: _reload,
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ReportBody extends StatelessWidget {
  const _ReportBody({
    required this.data,
    required this.baseUrl,
    required this.onRefresh,
  });

  final Map<String, dynamic> data;
  final String baseUrl;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final cards = _asList(data['cards']);
    final agent1 = _asMap(data['agent1']);
    final agent2 = _asMap(data['agent2']);
    final agent3 = _asMap(data['agent3']);
    final agent4 = _asMap(data['agent4']);
    final collaboration = _asMap(data['collaboration']);

    return RefreshIndicator(
      color: const Color(0xFFFFB36A),
      backgroundColor: const Color(0xFF1B1510),
      onRefresh: () async => onRefresh(),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
        padding: const EdgeInsets.fromLTRB(16, 6, 16, 24),
        children: [
          _UpdatedBanner(
            date: _string(data['date'], '-'),
            updatedAt: _dateTimeText(data['updated_at']),
          ),
          const SizedBox(height: 14),
          if (cards.isNotEmpty)
            SizedBox(
              height: 174,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: cards.length,
                separatorBuilder: (_, __) => const SizedBox(width: 12),
                itemBuilder: (context, index) => _AgentSummaryCard(agent: _asMap(cards[index])),
              ),
            ),
          const SizedBox(height: 18),
          _SectionCard(
            title: '최신 IT 뉴스',
            subtitle: '${_string(_asMap(agent1['collection_window'])['start'], '06:00')}~${_string(_asMap(agent1['collection_window'])['end'], '23:00')} 수집 · ${_int(agent1['selected_count'])}건 표시',
            icon: Icons.newspaper_rounded,
            child: _NewsList(items: _asList(agent1['items'])),
          ),
          _SectionCard(
            title: '블로그 초안',
            subtitle: '${_asList(agent2['drafts']).length}건 · Agent 02',
            icon: Icons.edit_note_rounded,
            child: _DraftList(drafts: _asList(agent2['drafts']), baseUrl: baseUrl),
          ),
          _SectionCard(
            title: 'Codex 승인 대기',
            subtitle: '${_asList(agent3['codex_pending_tasks']).length}건 · Agent 03',
            icon: Icons.code_rounded,
            child: _CodexList(tasks: _asList(agent3['codex_pending_tasks']), proposals: _asList(agent3['dev_proposals'])),
          ),
          _SectionCard(
            title: '유튜브 아이디어',
            subtitle: '${_asList(agent4['ideas']).length}건 · Agent 04',
            icon: Icons.video_collection_rounded,
            child: _IdeaList(ideas: _asList(agent4['ideas'])),
          ),
          _SectionCard(
            title: 'Agent 협업 로그',
            subtitle: '${_asList(collaboration['messages']).length}건',
            icon: Icons.hub_rounded,
            child: _CollaborationList(messages: _asList(collaboration['messages'])),
          ),
        ],
      ),
    );
  }
}

class _UpdatedBanner extends StatelessWidget {
  const _UpdatedBanner({required this.date, required this.updatedAt});

  final String date;
  final String updatedAt;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7EF),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: const Color(0x22FFB36A)),
      ),
      child: Row(
        children: [
          const Icon(Icons.insights_rounded, color: Color(0xFFC95C11)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              '$date 리포트 · $updatedAt 업데이트',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: const Color(0xFF5B4637),
                    fontWeight: FontWeight.w800,
                  ),
            ),
          ),
        ],
      ),
    );
  }
}

class _AgentSummaryCard extends StatelessWidget {
  const _AgentSummaryCard({required this.agent});

  final Map<String, dynamic> agent;

  @override
  Widget build(BuildContext context) {
    final agentId = _int(agent['agent_id']);
    final status = _string(agent['status'], 'idle');
    return Container(
      width: 248,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF9F3),
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: const Color(0x18C95C11)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 42,
                height: 42,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: const Color(0xFFFFE8D5),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Text(
                  agentId.toString().padLeft(2, '0'),
                  style: const TextStyle(color: Color(0xFFC95C11), fontWeight: FontWeight.w900),
                ),
              ),
              const Spacer(),
              _Pill(text: _statusLabel(status), tone: _statusTone(status)),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            _string(agent['title'], 'Agent $agentId'),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  color: const Color(0xFF2A211B),
                  fontWeight: FontWeight.w900,
                ),
          ),
          const SizedBox(height: 8),
          Text(
            _string(agent['latest_result_summary'], '최근 결과가 없습니다.'),
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: const Color(0xFF74665C),
                  height: 1.45,
                  fontWeight: FontWeight.w700,
                ),
          ),
        ],
      ),
    );
  }
}

class _SectionCard extends StatelessWidget {
  const _SectionCard({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.child,
  });

  final String title;
  final String subtitle;
  final IconData icon;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFFFFBF7),
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: const Color(0x16C95C11)),
        boxShadow: const [
          BoxShadow(
            color: Color(0x14000000),
            blurRadius: 16,
            offset: Offset(0, 10),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, color: const Color(0xFFC95C11)),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            color: const Color(0xFF2A211B),
                            fontWeight: FontWeight.w900,
                          ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      subtitle,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: const Color(0xFF8B7A6E),
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          child,
        ],
      ),
    );
  }
}

class _NewsList extends StatelessWidget {
  const _NewsList({required this.items});

  final List<dynamic> items;

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) return const _EmptyText('표시할 뉴스가 없습니다.');
    return Column(
      children: items.map((item) {
        final news = _asMap(item);
        return _CompactItem(
          title: _string(news['title'], '제목 없음'),
          meta: '${_string(news['source'], '출처 없음')} · ${_dateTimeText(news['published_at'])}',
        );
      }).toList(),
    );
  }
}

class _DraftList extends StatelessWidget {
  const _DraftList({required this.drafts, required this.baseUrl});

  final List<dynamic> drafts;
  final String baseUrl;

  @override
  Widget build(BuildContext context) {
    if (drafts.isEmpty) return const _EmptyText('블로그 초안이 없습니다.');
    return Column(
      children: drafts.map((item) {
        final draft = _asMap(item);
        final draftId = _int(draft['id']);
        return _CompactItem(
          title: _string(draft['title'], '제목 없음'),
          meta: '#$draftId · ${_string(draft['status'], '-')} · ${_dateTimeText(draft['created_at'])}',
          trailing: TextButton(
            onPressed: draftId <= 0 ? null : () => _openDraftPreview(context, baseUrl, draftId),
            child: const Text('미리보기'),
          ),
        );
      }).toList(),
    );
  }
}

class _CodexList extends StatelessWidget {
  const _CodexList({required this.tasks, required this.proposals});

  final List<dynamic> tasks;
  final List<dynamic> proposals;

  @override
  Widget build(BuildContext context) {
    final children = <Widget>[];
    for (final item in tasks.take(4)) {
      final task = _asMap(item);
      children.add(
        _CompactItem(
          title: _string(task['request'], '요청 내용 없음'),
          meta: '#${_int(task['id'])} · ${_string(task['status'], '-')} · ${_dateTimeText(task['updated_at'])}',
        ),
      );
    }
    for (final item in proposals.take(4)) {
      final proposal = _asMap(item);
      children.add(
        _CompactItem(
          title: _string(proposal['title'], '제안 제목 없음'),
          meta: '제안 #${_int(proposal['id'])} · ${_string(proposal['status'], '-')}',
        ),
      );
    }
    if (children.isEmpty) return const _EmptyText('Codex 승인 대기 항목이 없습니다.');
    return Column(children: children);
  }
}

class _IdeaList extends StatelessWidget {
  const _IdeaList({required this.ideas});

  final List<dynamic> ideas;

  @override
  Widget build(BuildContext context) {
    if (ideas.isEmpty) return const _EmptyText('유튜브 아이디어가 없습니다.');
    return Column(
      children: ideas.map((item) {
        final idea = _asMap(item);
        return _CompactItem(
          title: _string(idea['title'], '아이디어 없음'),
          meta: '#${_int(idea['task_id'])} · ${_string(idea['status'], '-')} · ${_dateTimeText(idea['updated_at'])}',
        );
      }).toList(),
    );
  }
}

class _CollaborationList extends StatelessWidget {
  const _CollaborationList({required this.messages});

  final List<dynamic> messages;

  @override
  Widget build(BuildContext context) {
    if (messages.isEmpty) return const _EmptyText('협업 로그가 없습니다.');
    return Column(
      children: messages.map((item) {
        final message = _asMap(item);
        final fromAgent = _int(message['from_agent_id']).toString().padLeft(2, '0');
        final toAgent = _int(message['to_agent_id']).toString().padLeft(2, '0');
        return _CompactItem(
          title: _string(message['message'], '메시지 없음'),
          meta: 'Agent $fromAgent → Agent $toAgent · ${_dateTimeText(message['created_at'])}',
        );
      }).toList(),
    );
  }
}

class _CompactItem extends StatelessWidget {
  const _CompactItem({
    required this.title,
    required this.meta,
    this.trailing,
  });

  final String title;
  final String meta;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(13),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7EF),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0x11C95C11)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: const Color(0xFF2F251E),
                        height: 1.4,
                        fontWeight: FontWeight.w900,
                      ),
                ),
                const SizedBox(height: 6),
                Text(
                  meta,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: const Color(0xFF8B7A6E),
                        height: 1.35,
                        fontWeight: FontWeight.w700,
                      ),
                ),
              ],
            ),
          ),
          if (trailing != null) ...[
            const SizedBox(width: 8),
            trailing!,
          ],
        ],
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.text, required this.tone});

  final String text;
  final Color tone;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: tone.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        text,
        style: TextStyle(color: tone, fontSize: 12, fontWeight: FontWeight.w900),
      ),
    );
  }
}

class _EmptyText extends StatelessWidget {
  const _EmptyText(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7EF),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0x11C95C11)),
      ),
      child: Text(
        text,
        textAlign: TextAlign.center,
        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: const Color(0xFF8B7A6E),
              fontWeight: FontWeight.w700,
            ),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off_rounded, color: Color(0xFFFFB4A2), size: 44),
            const SizedBox(height: 14),
            Text(
              '에이전트 리포트를 불러오지 못했습니다.',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    color: const Color(0xFFFFF7EF),
                    fontWeight: FontWeight.w900,
                  ),
            ),
            const SizedBox(height: 8),
            Text(
              message,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: const Color(0xFFD1BDB0),
                    height: 1.45,
                  ),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('다시 시도'),
            ),
          ],
        ),
      ),
    );
  }
}

Future<void> _openDraftPreview(BuildContext context, String baseUrl, int draftId) async {
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: const Color(0xFFFFFBF7),
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(26)),
    ),
    builder: (context) {
      return FutureBuilder<AgentBlogDraftDetail>(
        future: GyuvisApiClient(baseUrl: baseUrl).fetchBlogDraft(draftId),
        builder: (context, snapshot) {
          final bottomPadding = MediaQuery.of(context).padding.bottom;
          if (snapshot.connectionState == ConnectionState.waiting) {
            return SizedBox(
              height: 280 + bottomPadding,
              child: const Center(child: CircularProgressIndicator(color: Color(0xFFC95C11))),
            );
          }
          if (snapshot.hasError) {
            return Padding(
              padding: EdgeInsets.fromLTRB(20, 22, 20, 22 + bottomPadding),
              child: Text(
                '초안을 불러오지 못했습니다.\n${snapshot.error}',
                style: const TextStyle(color: Color(0xFF5B4637), height: 1.5),
              ),
            );
          }
          final draft = snapshot.data!;
          return DraggableScrollableSheet(
            expand: false,
            initialChildSize: 0.82,
            minChildSize: 0.42,
            maxChildSize: 0.95,
            builder: (context, scrollController) {
              return ListView(
                controller: scrollController,
                padding: EdgeInsets.fromLTRB(20, 18, 20, 22 + bottomPadding),
                children: [
                  Row(
                    children: [
                      Text(
                        '초안 #${draft.id}',
                        style: Theme.of(context).textTheme.labelLarge?.copyWith(
                              color: const Color(0xFFC95C11),
                              fontWeight: FontWeight.w900,
                            ),
                      ),
                      const Spacer(),
                      IconButton(
                        onPressed: () => Navigator.of(context).pop(),
                        icon: const Icon(Icons.close_rounded, color: Color(0xFF5B4637)),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    draft.title,
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(
                          color: const Color(0xFF2A211B),
                          fontWeight: FontWeight.w900,
                          height: 1.25,
                        ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    '${draft.platform} · ${draft.status} · ${_dateTimeText(draft.updatedAt)}',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: const Color(0xFF8B7A6E),
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                  const SizedBox(height: 18),
                  Text(
                    draft.body,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: const Color(0xFF3B3028),
                          height: 1.72,
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                ],
              );
            },
          );
        },
      );
    },
  );
}

List<dynamic> _asList(Object? value) => value is List ? value : const [];

Map<String, dynamic> _asMap(Object? value) => value is Map<String, dynamic> ? value : const {};

String _string(Object? value, String fallback) {
  final text = value?.toString().trim() ?? '';
  return text.isEmpty ? fallback : text;
}

int _int(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse(value?.toString() ?? '') ?? 0;
}

String _dateTimeText(Object? value) {
  final text = value?.toString().trim() ?? '';
  if (text.isEmpty) return '-';
  final normalized = text.replaceFirst('T', ' ');
  final parts = normalized.split('.');
  return parts.first;
}

String _statusLabel(String status) {
  switch (status) {
    case 'active':
      return '활성';
    case 'error':
      return '점검';
    case 'idle':
      return '대기';
    default:
      return status;
  }
}

Color _statusTone(String status) {
  switch (status) {
    case 'active':
      return const Color(0xFF0AA35B);
    case 'error':
      return const Color(0xFFD33C2F);
    default:
      return const Color(0xFFC95C11);
  }
}
