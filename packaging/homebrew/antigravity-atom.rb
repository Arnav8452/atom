class AntigravityAtom < Formula
  desc "Pixel mascot on Antigravity's prompt bar with 19 animated states and sustained moods"
  homepage "https://github.com/Arnav8452/atom"
  head "https://github.com/Arnav8452/atom.git", branch: "main"
  license "MIT"

  depends_on "python@3.12"

  def install
    libexec.install "atom_hook.py", "atom_launch.py", "atom_inject.js", "hooks.json", "plugin.json", "install.sh", "assets"
    chmod 0755, libexec/"atom_hook.py", libexec/"atom_launch.py", libexec/"install.sh"
    (bin/"antigravity-atom").write <<~EOS
      #!/usr/bin/env bash
      exec "#{Formula["python@3.12"].opt_bin}/python3" "#{libexec}/atom_launch.py" "$@"
    EOS
  end

  def caveats
    <<~EOS
      Run the installer once to create the Spotlight/Dock app bundle and link hooks:
        #{libexec}/install.sh
      Or launch directly (auto-links hooks on first run):
        antigravity-atom
    EOS
  end

  test do
    system "#{Formula["python@3.12"].opt_bin}/python3", "-m", "py_compile", "#{libexec}/atom_launch.py", "#{libexec}/atom_hook.py"
  end
end
