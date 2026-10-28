import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../api.dart';

class _Msg {
  _Msg(this.role, this.text, {this.meta, this.imageBytes, this.error = false});
  final String role;
  final String text;
  final String? meta;
  final Uint8List? imageBytes;
  final bool error;
}

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, required this.api});
  final AutoMotoApi api;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _picker = ImagePicker();
  final List<_Msg> _view = [];
  final List<Map<String, dynamic>> _history = [];
  String? _pendingImage; // data: URI
  Uint8List? _pendingBytes;
  bool _busy = false;

  Future<void> _pick(ImageSource src) async {
    final x = await _picker.pickImage(source: src, maxWidth: 1600, imageQuality: 80);
    if (x == null) return;
    final bytes = await x.readAsBytes();
    setState(() {
      _pendingBytes = bytes;
      _pendingImage = 'data:image/jpeg;base64,${base64Encode(bytes)}';
    });
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if ((text.isEmpty && _pendingImage == null) || _busy) return;
    final content = _pendingImage == null
        ? text
        : [
            {'type': 'text', 'text': text.isEmpty ? 'Describe this image.' : text},
            {'type': 'image_url', 'image_url': {'url': _pendingImage}},
          ];
    setState(() {
      _view.add(_Msg('user', text, imageBytes: _pendingBytes));
      _history.add({'role': 'user', 'content': content});
      _pendingImage = null;
      _pendingBytes = null;
      _busy = true;
      _input.clear();
    });
    try {
      final start = _history.length > 20 ? _history.length - 20 : 0;
      final r = await widget.api.chat(_history.sublist(start));
      final switched = r.tried.length > 1
          ? ' · switched: ${r.tried.map((t) => t['provider']).join(' → ')}'
          : '';
      setState(() {
        _history.add({'role': 'assistant', 'content': r.text});
        _view.add(_Msg('assistant', r.text, meta: '${r.provider} · ${r.model} · ${r.task}$switched'));
      });
    } catch (e) {
      setState(() {
        _history.removeLast();
        _view.add(_Msg('assistant', '✗ $e', error: true));
      });
    } finally {
      setState(() => _busy = false);
      await Future<void>.delayed(const Duration(milliseconds: 50));
      if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Column(children: [
      ListTile(
        title: const Text('AutoMoto AI · Cousin', style: TextStyle(fontWeight: FontWeight.bold)),
        subtitle: const Text('Multi-AI · auto-failover · vision for photos'),
        trailing: IconButton(
          tooltip: 'New chat',
          icon: const Icon(Icons.refresh),
          onPressed: () => setState(() {
            _view.clear();
            _history.clear();
          }),
        ),
      ),
      Expanded(
        child: _view.isEmpty
            ? const Center(child: Text('Hey cousin 👋  Ask anything or snap a photo.'))
            : ListView.builder(
                controller: _scroll,
                padding: const EdgeInsets.all(12),
                itemCount: _view.length,
                itemBuilder: (_, i) {
                  final m = _view[i];
                  final mine = m.role == 'user';
                  return Align(
                    alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
                    child: Container(
                      margin: const EdgeInsets.symmetric(vertical: 4),
                      padding: const EdgeInsets.all(12),
                      constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * .85),
                      decoration: BoxDecoration(
                        color: m.error
                            ? scheme.errorContainer
                            : mine
                                ? scheme.primaryContainer
                                : scheme.surfaceContainerHighest,
                        borderRadius: BorderRadius.circular(14),
                      ),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        if (m.imageBytes != null)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 6),
                            child: ClipRRect(
                              borderRadius: BorderRadius.circular(8),
                              child: Image.memory(m.imageBytes!, height: 140),
                            ),
                          ),
                        if (m.text.isNotEmpty) SelectableText(m.text),
                        if (m.meta != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 6),
                            child: Text(m.meta!, style: Theme.of(context).textTheme.labelSmall),
                          ),
                      ]),
                    ),
                  );
                },
              ),
      ),
      if (_busy) const LinearProgressIndicator(),
      if (_pendingImage != null)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: Row(children: [
            const Icon(Icons.image, size: 18),
            const SizedBox(width: 6),
            const Expanded(child: Text('Image attached — a vision AI will answer')),
            IconButton(
              icon: const Icon(Icons.close),
              onPressed: () => setState(() {
                _pendingImage = null;
                _pendingBytes = null;
              }),
            ),
          ]),
        ),
      Padding(
        padding: const EdgeInsets.fromLTRB(8, 4, 8, 8),
        child: Row(children: [
          IconButton(tooltip: 'Camera', icon: const Icon(Icons.photo_camera_outlined), onPressed: () => _pick(ImageSource.camera)),
          IconButton(tooltip: 'Photos', icon: const Icon(Icons.photo_outlined), onPressed: () => _pick(ImageSource.gallery)),
          Expanded(
            child: TextField(
              controller: _input,
              minLines: 1,
              maxLines: 5,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _send(),
              decoration: const InputDecoration(hintText: 'Message AutoMoto…', border: OutlineInputBorder()),
            ),
          ),
          const SizedBox(width: 6),
          IconButton.filled(onPressed: _busy ? null : _send, icon: const Icon(Icons.send)),
        ]),
      ),
    ]);
  }
}
