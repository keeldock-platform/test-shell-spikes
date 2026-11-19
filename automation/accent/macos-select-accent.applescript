-- Disposable macOS CI runner only. Never run this on a personal workstation.
-- Argument 1 is an English accessibility label exposed by the current Appearance pane.
on run argv
	if (count of argv) is 0 then error "Pass an accent label such as Purple or Orange."
	set targetLabel to item 1 of argv
	tell application "System Settings" to activate
	open location "x-apple.systempreferences:com.apple.Appearance-Settings.extension"
	delay 2

	tell application "System Events"
		tell process "System Settings"
			set frontmost to true
			set deadline to (current date) + 20
			repeat while (count of windows) is 0 and (current date) is less than deadline
				delay 0.25
			end repeat
			if (count of windows) is 0 then error "Appearance pane did not open."
			set candidates to entire contents of window 1
			repeat with candidate in candidates
				try
					if (name of candidate as text) is targetLabel then
						set candidateRole to role of candidate
						if candidateRole is "AXRadioButton" or candidateRole is "AXButton" then
							click candidate
							delay 1
							return "selected:" & targetLabel
						end if
					end if
				end try
			end repeat
		end tell
	end tell
	error "Accent label not found in the Appearance accessibility tree: " & targetLabel
end run
