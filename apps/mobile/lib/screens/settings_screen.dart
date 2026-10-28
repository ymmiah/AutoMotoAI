import 'package:flutter/material.dart';

import '../api.dart';

const _labels = {
  'nim': 'NVIDIA NIM (free)',
  'gemini': 'Google Gemini (free)',
  'groq': 'Groq (free)',
  'openrouter': 'OpenRouter (free models)',
  'openai': 'OpenAI (paid)',
  'claude': 'Anthropic Claude (paid)',
};

/// Server connection + bring-your-own keys, all in secure storage.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, required this.api});
  final AutoMotoApi api;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _server = TextEditingController();
  final _token = TextEditingController();
  final _keys = {for (final id in providerIds) id: TextEditingController()};
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    _server.text = await widget.api.serverUrl();
    _token.text = await widget.api.apiToken() ?? '';
    for (final id in providerIds) {
      _keys[id]!.text = await widget.api.providerKey(id) ?? '';
    }
    setState(() => _loaded = true);
  }

  Future<void> _save() async {
    await widget.api.setServerUrl(_server.text);
    await widget.api.setApiToken(_token.text);
    for (final id in providerIds) {
      await widget.api.setProviderKey(id, _keys[id]!.text);
    }
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Saved to secure storage')));
    }
  }

  Future<void> _forget() async {
    await widget.api.forgetAll();
    await _load();
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('All keys wiped from this device')));
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_loaded) return const Center(child: CircularProgressIndicator());
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text('Server', style: Theme.of(context).textTheme.titleMedium),
      const SizedBox(height: 8),
      TextField(
        controller: _server,
        keyboardType: TextInputType.url,
        decoration: const InputDecoration(
          labelText: 'AutoMoto server URL',
          helperText: 'Emulator: http://10.0.2.2:8765 · Phone: http://<your-PC-LAN-IP>:8765',
          border: OutlineInputBorder(),
        ),
      ),
      const SizedBox(height: 12),
      TextField(
        controller: _token,
        obscureText: true,
        decoration: const InputDecoration(
          labelText: 'AUTOMOTO_API_TOKEN',
          helperText: 'Same value as on the server (needed for non-local access)',
          border: OutlineInputBorder(),
        ),
      ),
      const SizedBox(height: 24),
      Text('Your AI keys (optional)', style: Theme.of(context).textTheme.titleMedium),
      const Text('Stored in the iOS Keychain / Android Keystore. Sent only to your AutoMoto server with each request; never logged.'),
      const SizedBox(height: 8),
      for (final id in providerIds)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: TextField(
            controller: _keys[id],
            obscureText: true,
            autocorrect: false,
            enableSuggestions: false,
            decoration: InputDecoration(labelText: _labels[id], border: const OutlineInputBorder()),
          ),
        ),
      const SizedBox(height: 8),
      Row(children: [
        Expanded(child: FilledButton(onPressed: _save, child: const Text('Save'))),
        const SizedBox(width: 12),
        Expanded(child: OutlinedButton(onPressed: _forget, child: const Text('Forget everything'))),
      ]),
    ]);
  }
}
